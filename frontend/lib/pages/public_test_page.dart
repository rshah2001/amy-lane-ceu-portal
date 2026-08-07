import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/api_client.dart';
import '../widgets/common.dart';

class PublicTestPage extends StatefulWidget {
  const PublicTestPage({
    super.key,
    required this.api,
    required this.token,
    this.inviteNonce,
    this.prefillName,
    this.prefillEmail,
  });
  final ApiClient api;
  final String token;

  /// Per-attendee secret from the `k` parameter of an emailed invite link.
  ///
  /// When present the server credits the attendee it was minted for and skips
  /// name matching entirely, so neither a nickname typed into the form nor a
  /// colleague's address can move somebody else's score. Absent for the
  /// printed QR sheet and for the walk-in check-in hand-off, which are one
  /// shared link for the whole room — those still work, they just fall back to
  /// matching on the address supplied.
  final String? inviteNonce;
  final String? prefillName;
  final String? prefillEmail;

  @override
  State<PublicTestPage> createState() => _PublicTestPageState();
}

class _PublicTestPageState extends State<PublicTestPage> {
  final formKey = GlobalKey<FormState>();
  final name = TextEditingController();
  final email = TextEditingController();
  // Keyed + focusable so a failed submit can land the caret on the field that
  // actually failed, and say why.
  final nameField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'full name'),
  );
  final emailField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'email address'),
  );
  Map<String, dynamic>? test;
  final selected = <String, int>{};
  String? error;
  bool saving = false;
  Map<String, dynamic>? result;

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
      final data = await widget.api.get('/public/tests/${widget.token}') as Map<String, dynamic>;
      if (mounted) setState(() => test = data);
    } catch (exception) {
      if (mounted) _fail(exception);
    }
  }

  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
  }

  /// `?k=<nonce>` when this page was opened from an emailed invite, else empty.
  /// Encoded rather than interpolated raw, so a mangled link comes back as a
  /// clean 422 from the server's length bound instead of a malformed URL.
  String get _nonceQuery {
    final nonce = widget.inviteNonce;
    if (nonce == null || nonce.isEmpty) return '';
    return '?k=${Uri.encodeQueryComponent(nonce)}';
  }

  Future<void> submit() async {
    if (!validateAndFocusFirstError(context, formKey, [nameField, emailField])) return;
    final questions = test!['questions'] as List;
    if (selected.length < questions.length) {
      const message = 'Please answer every question before submitting.';
      setState(() => error = message);
      announceToScreenReader(context, message);
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final response = await widget.api.post('/public/tests/${widget.token}$_nonceQuery', {
        'full_name': name.text.trim(),
        'email': email.text.trim(),
        'answers': selected,
      }) as Map<String, dynamic>;
      if (mounted) setState(() => result = response);
    } catch (exception) {
      if (mounted) _fail(exception);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  /// The backend keeps the latest attempt, so a failed attendee can simply
  /// retake the test instead of chasing down the organizer.
  void _retake() {
    setState(() {
      result = null;
      selected.clear();
      error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        title: const Text('CEU Post-Test'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: maxPublicWidth),
            child: error != null && test == null
                ? ErrorPanel(message: error!, onRetry: load)
                : test == null
                    ? const LoadingPanel(label: 'Loading the post-test')
                    : result != null
                        ? _ResultCard(result: result!, onTryAgain: _retake)
                        : _buildForm(),
          ),
        ),
      ),
    );
  }

  Widget _buildForm() {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final questions = test!['questions'] as List;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Space.xl),
        child: Form(
          key: formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Heading(
                child: Text(
                  test!['event_title'] as String,
                  style: theme.textTheme.headlineMedium,
                ),
              ),
              const SizedBox(height: Space.xxs + 1),
              Text(
                '${DateFormat.yMMMMd().format(DateTime.parse(test!['event_date'] as String))} • ${test!['presenter_name'] ?? 'CEU Training'}',
                style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
              ),
              const SizedBox(height: Space.xxs + 2),
              Text(
                'A score of 80% or higher is required to earn your certificate.',
                style: theme.textTheme.bodySmall?.copyWith(color: colors.textSecondary),
              ),
              const SizedBox(height: Space.xl - 2),
              TextFormField(
                key: nameField.key,
                focusNode: nameField.focus,
                controller: name,
                autofillHints: const [AutofillHints.name],
                textCapitalization: TextCapitalization.words,
                textInputAction: TextInputAction.next,
                decoration: const InputDecoration(labelText: 'Full name'),
                validator: (value) => value == null || value.trim().length < 2 ? 'Enter your name' : null,
              ),
              const SizedBox(height: Space.sm + 2),
              TextFormField(
                key: emailField.key,
                focusNode: emailField.focus,
                controller: email,
                keyboardType: TextInputType.emailAddress,
                autofillHints: const [AutofillHints.email],
                textInputAction: TextInputAction.done,
                decoration: const InputDecoration(labelText: 'Email address'),
                validator: emailValidator,
              ),
              for (var i = 0; i < questions.length; i++) ...[
                const SizedBox(height: Space.xl - 2),
                Text(
                  '${i + 1}. ${questions[i]['prompt']}',
                  style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
                RadioGroup<int>(
                  groupValue: selected[questions[i]['id']],
                  onChanged: (value) => setState(() => selected[questions[i]['id'] as String] = value!),
                  child: Column(
                    children: [
                      for (var c = 0; c < (questions[i]['choices'] as List).length; c++)
                        RadioListTile<int>(
                          contentPadding: EdgeInsets.zero,
                          dense: true,
                          value: c,
                          title: Text((questions[i]['choices'] as List)[c] as String),
                        ),
                    ],
                  ),
                ),
              ],
              if (error != null) ...[
                const SizedBox(height: Space.sm),
                FormErrorText(error!),
              ],
              const SizedBox(height: Space.xl),
              ElevatedButton.icon(
                onPressed: saving ? null : submit,
                icon: const Icon(Icons.check_circle_outline),
                label: Text(saving ? 'Submitting...' : 'Submit test'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.result, required this.onTryAgain});
  final Map<String, dynamic> result;

  /// Clears the previous attempt so the attendee can retake immediately.
  final VoidCallback onTryAgain;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final passed = result['passed'] as bool;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Space.xxxl - 8),
        // The result is the whole point of the page and it appears without a
        // navigation, so it is announced rather than silently swapped in.
        child: Semantics(
          liveRegion: true,
          container: true,
          child: Column(
            children: [
              ExcludeSemantics(
                child: Icon(
                  passed ? Icons.verified : Icons.error_outline,
                  color: passed ? colors.success : colors.danger,
                  size: 56,
                ),
              ),
              const SizedBox(height: Space.md),
              Heading(
                child: Text(
                  '${result['score']}%',
                  style: theme.textTheme.displayMedium,
                  semanticsLabel: passed
                      ? 'Passed with ${result['score']} percent'
                      : 'Did not pass. Scored ${result['score']} percent',
                ),
              ),
              const SizedBox(height: Space.xxs),
              Text(
                '${result['correct']} of ${result['total']} correct',
                style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
              ),
              const SizedBox(height: Space.sm),
              Text(
                passed
                    ? 'You passed. Your certificate will be issued after the organizer reviews the session.'
                    : 'A score of 80% is required. You can retake the test right away — your latest attempt is the one that counts.',
                textAlign: TextAlign.center,
              ),
              if (!passed) ...[
                const SizedBox(height: Space.lg),
                ElevatedButton.icon(
                  onPressed: onTryAgain,
                  icon: const Icon(Icons.replay),
                  label: const Text('Try again'),
                ),
                const SizedBox(height: Space.sm),
                Text(
                  'Having trouble? Contact the event organizer for help.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall?.copyWith(color: colors.textSecondary),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
