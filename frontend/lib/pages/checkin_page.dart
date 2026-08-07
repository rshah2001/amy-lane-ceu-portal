import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../widgets/common.dart';
import 'public_survey_page.dart';
import 'public_test_page.dart';

class CheckinPage extends StatefulWidget {
  const CheckinPage({
    super.key,
    required this.api,
    required this.token,
    this.prefillName,
    this.prefillEmail,
  });
  final ApiClient api;
  final String token;
  final String? prefillName;
  final String? prefillEmail;

  @override
  State<CheckinPage> createState() => _CheckinPageState();
}

class _CheckinPageState extends State<CheckinPage> {
  final formKey = GlobalKey<FormState>();
  final name = TextEditingController();
  final email = TextEditingController();
  final nameField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'full name'),
  );
  final emailField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'email address'),
  );
  Map<String, dynamic>? event;
  Map<String, dynamic> nextSteps = {};
  // Two separate failures, because they need opposite treatment: a failed
  // *load* means there is no form to show (fatal, full-page panel), while a
  // failed *submit* must leave the filled-in form on screen so the attendee
  // can simply press the button again. Collapsing them into one field hid the
  // form behind a permanent error panel after any submit hiccup.
  String? loadError;
  String? submitError;
  bool submitted = false;
  bool saving = false;

  @override
  void initState() {
    super.initState();
    if (widget.prefillName != null) name.text = widget.prefillName!;
    if (widget.prefillEmail != null) email.text = widget.prefillEmail!;
    load();
  }

  @override
  void dispose() {
    name.dispose();
    email.dispose();
    nameField.focus.dispose();
    emailField.focus.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final result = await widget.api.get('/public/checkin/${widget.token}') as Map<String, dynamic>;
      // Clear the error on success, or "Retry" would fetch the event fine and
      // still leave the failure panel on screen forever.
      if (mounted) {
        setState(() {
          event = result;
          loadError = null;
        });
      }
    } catch (exception) {
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => loadError = message);
        announceToScreenReader(context, message);
      }
    }
  }

  Future<void> submit() async {
    if (!validateAndFocusFirstError(context, formKey, [nameField, emailField])) return;
    setState(() {
      saving = true;
      submitError = null;
    });
    try {
      final result = await widget.api.post('/public/checkin/${widget.token}', {
        'full_name': name.text.trim(),
        'email': email.text.trim(),
      });
      if (mounted) {
        setState(() {
          nextSteps = (result as Map?)?.cast<String, dynamic>() ?? {};
          submitted = true;
        });
      }
    } catch (exception) {
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => submitError = message);
        announceToScreenReader(context, message);
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  // After check-in the attendee goes straight to the post-test/survey with
  // their name and email carried over, so nothing gets typed twice.
  List<Widget> _nextStepButtons() {
    final buttons = <Widget>[];
    void addButton(String label, IconData icon, VoidCallback onPressed) {
      buttons.add(const SizedBox(height: Space.sm + 2));
      buttons.add(ElevatedButton.icon(onPressed: onPressed, icon: Icon(icon), label: Text(label)));
    }

    final enteredName = name.text.trim();
    final enteredEmail = email.text.trim();
    if (nextSteps['test_token'] != null) {
      addButton('Continue to the post-test', Icons.quiz, () {
        Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => PublicTestPage(
            api: widget.api,
            token: nextSteps['test_token'] as String,
            prefillName: enteredName,
            prefillEmail: enteredEmail,
          ),
        ));
      });
    } else if (nextSteps['post_test_url'] != null) {
      addButton('Open the post-test', Icons.quiz, () {
        launchUrl(Uri.parse(nextSteps['post_test_url'] as String), webOnlyWindowName: '_blank');
      });
    }
    if (nextSteps['survey_token'] != null) {
      addButton('Take the feedback survey', Icons.rate_review, () {
        Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => PublicSurveyPage(
            api: widget.api,
            token: nextSteps['survey_token'] as String,
            prefillName: enteredName,
            prefillEmail: enteredEmail,
          ),
        ));
      });
    } else if (nextSteps['external_survey_url'] != null) {
      addButton('Take the feedback survey', Icons.rate_review, () {
        launchUrl(Uri.parse(nextSteps['external_survey_url'] as String), webOnlyWindowName: '_blank');
      });
    }
    return buttons;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        title: const Text('Event Check-In'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: maxPublicWidth),
            child: loadError != null
                ? ErrorPanel(message: loadError!, onRetry: load)
                : event == null
                    ? const LoadingPanel(label: 'Loading the check-in page')
                    : submitted
                        ? Card(
                            child: Padding(
                              padding: const EdgeInsets.all(Space.xxxl - 8),
                              child: Semantics(
                                liveRegion: true,
                                container: true,
                                child: Column(
                                children: [
                                  ExcludeSemantics(
                                    child: Icon(Icons.verified, color: colors.success, size: 52),
                                  ),
                                  const SizedBox(height: Space.md),
                                  Heading(
                                    child: Text(
                                      "You're checked in",
                                      style: theme.textTheme.headlineMedium,
                                    ),
                                  ),
                                  const SizedBox(height: Space.xs),
                                  Text(
                                    nextSteps.isEmpty
                                        ? 'Your attendance has been recorded. Remember to complete the post-test to earn your certificate.'
                                        : 'Your attendance has been recorded. Finish the steps below to earn your certificate.',
                                    textAlign: TextAlign.center,
                                  ),
                                  ..._nextStepButtons(),
                                ],
                                ),
                              ),
                            ),
                          )
                        : Card(
                            child: Padding(
                              padding: const EdgeInsets.all(Space.xl),
                              child: Form(
                                key: formKey,
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.stretch,
                                  children: [
                                    Heading(
                                      child: Text(
                                        event!['event_title'] as String,
                                        style: theme.textTheme.headlineMedium,
                                      ),
                                    ),
                                    const SizedBox(height: Space.xxs + 1),
                                    Text(
                                      '${DateFormat.yMMMMd().format(DateTime.parse(event!['event_date'] as String))}'
                                      '${event!['location'] != null ? ' • ${event!['location']}' : ''}',
                                      style: theme.textTheme.bodyMedium
                                          ?.copyWith(color: colors.textSecondary),
                                    ),
                                    const SizedBox(height: Space.lg),
                                    Text(
                                      'Confirm your attendance for this event.',
                                      style: theme.textTheme.bodyMedium
                                          ?.copyWith(color: colors.textSecondary),
                                    ),
                                    const SizedBox(height: Space.md),
                                    TextFormField(
                                      key: nameField.key,
                                      focusNode: nameField.focus,
                                      controller: name,
                                      autofillHints: const [AutofillHints.name],
                                      textCapitalization: TextCapitalization.words,
                                      textInputAction: TextInputAction.next,
                                      decoration: const InputDecoration(labelText: 'Full name'),
                                      validator: (v) => v == null || v.trim().length < 2 ? 'Enter your name' : null,
                                    ),
                                    const SizedBox(height: Space.sm + 2),
                                    TextFormField(
                                      key: emailField.key,
                                      focusNode: emailField.focus,
                                      controller: email,
                                      keyboardType: TextInputType.emailAddress,
                                      autofillHints: const [AutofillHints.email],
                                      textInputAction: TextInputAction.done,
                                      onFieldSubmitted: (_) => submit(),
                                      decoration: const InputDecoration(labelText: 'Email address'),
                                      validator: emailValidator,
                                    ),
                                    if (submitError != null) ...[
                                      const SizedBox(height: Space.sm),
                                      FormErrorText(submitError!),
                                    ],
                                    const SizedBox(height: Space.xl - 2),
                                    ElevatedButton.icon(
                                      onPressed: saving ? null : submit,
                                      icon: const Icon(Icons.how_to_reg),
                                      label: Text(saving ? 'Checking in...' : 'Check in'),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
          ),
        ),
      ),
    );
  }
}
