import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/api_client.dart';
import '../widgets/common.dart';

class PublicSurveyPage extends StatefulWidget {
  const PublicSurveyPage({
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
  State<PublicSurveyPage> createState() => _PublicSurveyPageState();
}

class _PublicSurveyPageState extends State<PublicSurveyPage> {
  final formKey = GlobalKey<FormState>();
  final businessLocation = TextEditingController();
  final name = TextEditingController();
  final email = TextEditingController();
  Map<String, dynamic>? survey;
  final answers = <String, TextEditingController>{};
  final choiceAnswers = <String, String?>{};
  final nameField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'full name'),
  );
  final emailField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'email address'),
  );
  String? error;
  bool submitted = false;
  bool saving = false;

  @override
  void dispose() {
    businessLocation.dispose();
    name.dispose();
    email.dispose();
    // One per free-text question, created in load().
    for (final controller in answers.values) {
      controller.dispose();
    }
    nameField.focus.dispose();
    emailField.focus.dispose();
    super.dispose();
  }

  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
  }

  @override
  void initState() {
    super.initState();
    if (widget.prefillName != null) name.text = widget.prefillName!;
    if (widget.prefillEmail != null) email.text = widget.prefillEmail!;
    load();
  }

  Future<void> load() async {
    try {
      final result = await widget.api.get('/public/surveys/${widget.token}') as Map<String, dynamic>;
      // Nothing below is worth doing for a page that has gone away — and the
      // controllers built there would never be disposed, because dispose() has
      // already run.
      if (!mounted) return;
      // Retry replaces the question list, so the controllers belonging to the
      // old questions have to go with them. Overwriting the map instead left
      // one live TextEditingController per free-text question, attached to
      // nothing, on every attempt — and this is the page an attendee reloads on
      // conference-centre wifi.
      for (final controller in answers.values) {
        controller.dispose();
      }
      answers.clear();
      choiceAnswers.clear();
      for (final question in result['questions'] as List) {
        if (question['type'] == 'choice') {
          choiceAnswers[question['id'] as String] = null;
        } else {
          answers[question['id'] as String] = TextEditingController();
        }
      }
      setState(() => survey = result);
    } catch (exception) {
      if (mounted) _fail(exception);
    }
  }

  Future<void> submit() async {
    if (!validateAndFocusFirstError(context, formKey, [nameField, emailField])) return;
    // Questions are optional — only send what was actually written, but ask
    // for at least one answer so an entirely blank survey isn't recorded.
    final filledAnswers = {
      for (final entry in answers.entries)
        if (entry.value.text.trim().isNotEmpty) entry.key: entry.value.text.trim(),
      for (final entry in choiceAnswers.entries)
        if (entry.value != null) entry.key: entry.value!,
    };
    if (filledAnswers.isEmpty) {
      const message = 'Please answer at least one question.';
      setState(() => error = message);
      announceToScreenReader(context, message);
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      // Identity fields are optional (anonymous feedback is allowed); blanks
      // are sent as null so nothing empty is stored.
      await widget.api.post('/public/surveys/${widget.token}', {
        'business_location': businessLocation.text.trim().isEmpty ? null : businessLocation.text.trim(),
        'full_name': name.text.trim().isEmpty ? null : name.text.trim(),
        'email': email.text.trim().isEmpty ? null : email.text.trim(),
        'answers': filledAnswers,
      });
      if (mounted) setState(() => submitted = true);
    } catch (exception) {
      if (mounted) _fail(exception);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Scaffold(
      appBar: AppBar(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        title: const Text('CEU Course Feedback'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: maxPublicWidth),
            child: error != null && survey == null
                ? ErrorPanel(message: error!, onRetry: load)
                : survey == null
                    ? const LoadingPanel(label: 'Loading the feedback survey')
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
                                      child: Icon(Icons.check_circle, color: colors.success, size: 52),
                                    ),
                                    const SizedBox(height: Space.md),
                                    Heading(
                                      child: Text('Thank you', style: theme.textTheme.headlineLarge),
                                    ),
                                    const SizedBox(height: Space.xs),
                                    const Text('Your feedback has been recorded.'),
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
                                        survey!['event_title'] as String,
                                        style: theme.textTheme.headlineMedium,
                                      ),
                                    ),
                                    const SizedBox(height: Space.xxs + 1),
                                    Text(
                                      '${DateFormat.yMMMMd().format(DateTime.parse(survey!['event_date'] as String))} • ${survey!['presenter_name'] ?? 'CEU Training'}',
                                      style: theme.textTheme.bodyMedium
                                          ?.copyWith(color: colors.textSecondary),
                                    ),
                                    const SizedBox(height: Space.xl),
                                    TextFormField(
                                      controller: businessLocation,
                                      textCapitalization: TextCapitalization.words,
                                      textInputAction: TextInputAction.next,
                                      decoration: const InputDecoration(labelText: 'Business Name / Location (optional)'),
                                    ),
                                    const SizedBox(height: Space.sm + 2),
                                    TextFormField(
                                      key: nameField.key,
                                      focusNode: nameField.focus,
                                      controller: name,
                                      autofillHints: const [AutofillHints.name],
                                      textCapitalization: TextCapitalization.words,
                                      textInputAction: TextInputAction.next,
                                      decoration: const InputDecoration(labelText: 'Full name (optional)'),
                                      // Blank is fine (anonymous feedback); a provided name
                                      // must still be at least 2 characters.
                                      validator: (value) {
                                        final text = value?.trim() ?? '';
                                        return text.isEmpty || text.length >= 2 ? null : 'Enter your name';
                                      },
                                    ),
                                    const SizedBox(height: Space.sm + 2),
                                    TextFormField(
                                      key: emailField.key,
                                      focusNode: emailField.focus,
                                      controller: email,
                                      keyboardType: TextInputType.emailAddress,
                                      autofillHints: const [AutofillHints.email],
                                      textInputAction: TextInputAction.next,
                                      decoration: const InputDecoration(labelText: 'Email address (optional)'),
                                      validator: optionalEmailValidator,
                                    ),
                                    const SizedBox(height: Space.md + 2),
                                    Text(
                                      'Answer as many questions as you like — every question is optional.',
                                      style: theme.textTheme.bodySmall
                                          ?.copyWith(color: colors.textSecondary),
                                    ),
                                    for (final question in survey!['questions'] as List) ...[
                                      const SizedBox(height: Space.md + 2),
                                      if (question['type'] == 'choice')
                                        InputDecorator(
                                          decoration: InputDecoration(
                                            labelText: question['label'] as String,
                                            contentPadding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                                          ),
                                          child: RadioGroup<String>(
                                            groupValue: choiceAnswers[question['id']],
                                            onChanged: (value) => setState(
                                              () => choiceAnswers[question['id'] as String] = value,
                                            ),
                                            child: Column(
                                              children: [
                                                for (final option in (question['options'] as List?) ?? const [])
                                                  RadioListTile<String>(
                                                    value: option.toString(),
                                                    title: Text(option.toString()),
                                                    contentPadding: EdgeInsets.zero,
                                                    dense: true,
                                                  ),
                                              ],
                                            ),
                                          ),
                                        )
                                      else
                                        TextFormField(
                                          controller: answers[question['id']],
                                          maxLines: 3,
                                          textCapitalization: TextCapitalization.sentences,
                                          decoration: InputDecoration(labelText: question['label'] as String),
                                        ),
                                    ],
                                    if (error != null) ...[
                                      const SizedBox(height: Space.sm),
                                      FormErrorText(error!),
                                    ],
                                    const SizedBox(height: Space.xl),
                                    ElevatedButton.icon(
                                      onPressed: saving ? null : submit,
                                      icon: const Icon(Icons.send_outlined),
                                      label: Text(saving ? 'Submitting...' : 'Submit feedback'),
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
