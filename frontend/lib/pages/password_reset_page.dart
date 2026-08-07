import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../widgets/common.dart';

/// Landing page for the `?reset=<token>` link in a password-reset email.
///
/// Public, like the check-in and survey pages: whoever follows this link
/// cannot sign in by definition, so it must work with no session at all. It is
/// reached from [main] before the router, the same way the QR-code pages are.
class PasswordResetPage extends StatefulWidget {
  const PasswordResetPage({super.key, required this.api, required this.token});

  final ApiClient api;
  final String token;

  @override
  State<PasswordResetPage> createState() => _PasswordResetPageState();
}

class _PasswordResetPageState extends State<PasswordResetPage> {
  final formKey = GlobalKey<FormState>();
  final password = TextEditingController();
  final confirm = TextEditingController();
  final passwordField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'new password'),
  );
  final confirmField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'confirm password'),
  );

  bool saving = false;
  bool done = false;
  String? error;
  bool obscure = true;

  @override
  void dispose() {
    password.dispose();
    confirm.dispose();
    passwordField.focus.dispose();
    confirmField.focus.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (!validateAndFocusFirstError(context, formKey, [passwordField, confirmField])) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.api.post('/auth/reset-password', {
        'token': widget.token,
        'new_password': password.text,
      });
      if (mounted) setState(() => done = true);
    } catch (exception) {
      if (mounted) {
        // The server answers a bad, spent or expired token with one
        // deliberately identical message, so there is nothing to add here
        // beyond showing it — guessing at which case it was would only
        // recreate the enumeration hole the server closed.
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
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
        title: const Text('Set a new password'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(Space.xl),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: maxFormWidth),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(Space.xl),
                child: done ? _success(theme, colors) : _form(theme, colors),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _success(ThemeData theme, PortalColors colors) {
    return Semantics(
      liveRegion: true,
      container: true,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ExcludeSemantics(child: Icon(Icons.check_circle_outline, color: colors.success, size: 48)),
          const SizedBox(height: Space.md),
          Heading(child: Text('Password updated', style: theme.textTheme.headlineMedium)),
          const SizedBox(height: Space.xs),
          Text(
            'You can now sign in with your new password.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
          ),
          const SizedBox(height: Space.lg),
          ElevatedButton(
            // A document load rather than a router push: this page is built
            // outside the router, straight off the emailed link, so there is no
            // navigation stack to return into. Navigating to the bare origin
            // also drops the ?reset= token from the address bar, so the spent
            // token stops sitting in history and in any shared screenshot.
            onPressed: () => launchUrl(
              Uri.parse(Uri.base.origin),
              webOnlyWindowName: '_self',
            ),
            child: const Text('Go to sign in'),
          ),
        ],
      ),
    );
  }

  Widget _form(ThemeData theme, PortalColors colors) {
    return Form(
      key: formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Heading(child: Text('Choose a new password', style: theme.textTheme.headlineMedium)),
          const SizedBox(height: Space.xs),
          Text(
            'This link can only be used once. Pick something at least 8 characters long.',
            style: theme.textTheme.bodyMedium?.copyWith(color: colors.textSecondary),
          ),
          const SizedBox(height: Space.lg),
          TextFormField(
            key: passwordField.key,
            focusNode: passwordField.focus,
            controller: password,
            obscureText: obscure,
            autofillHints: const [AutofillHints.newPassword],
            decoration: InputDecoration(
              labelText: 'New password',
              suffixIcon: IconButton(
                tooltip: obscure ? 'Show password' : 'Hide password',
                icon: Icon(obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                onPressed: () => setState(() => obscure = !obscure),
              ),
            ),
            validator: (value) {
              final text = value ?? '';
              // Mirrors the server's PASSWORD_MIN_LENGTH / PASSWORD_MAX_LENGTH
              // so the rejection happens here rather than as a 422.
              if (text.length < 8) return 'Use at least 8 characters';
              if (text.length > 128) return 'Use 128 characters or fewer';
              return null;
            },
          ),
          const SizedBox(height: Space.md),
          TextFormField(
            key: confirmField.key,
            focusNode: confirmField.focus,
            controller: confirm,
            obscureText: obscure,
            autofillHints: const [AutofillHints.newPassword],
            decoration: const InputDecoration(labelText: 'Confirm new password'),
            onFieldSubmitted: (_) => submit(),
            validator: (value) => value == password.text ? null : 'The two passwords do not match',
          ),
          if (error != null) ...[
            const SizedBox(height: Space.md),
            FormErrorText(error!),
          ],
          const SizedBox(height: Space.lg),
          ElevatedButton(
            onPressed: saving ? null : submit,
            child: saving
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Set new password'),
          ),
        ],
      ),
    );
  }
}
