import 'package:flutter/material.dart';

import '../core/session.dart';
import '../widgets/common.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key, required this.session});
  final SessionController session;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final formKey = GlobalKey<FormState>();
  final email = TextEditingController();
  final password = TextEditingController();
  final emailField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'email address'),
  );
  final passwordField = (
    key: GlobalKey<FormFieldState<String>>(),
    focus: FocusNode(debugLabel: 'password'),
  );
  bool obscure = true;

  /// The last sign-in failure that was spoken, so a rebuild doesn't repeat it.
  String? announcedError;

  @override
  void initState() {
    super.initState();
    // Rebuild for loading/error changes triggered by the session controller.
    widget.session.addListener(_onSessionChanged);
  }

  void _onSessionChanged() {
    if (!mounted) return;
    setState(() {});
    // A wrong password re-renders the same page with a red line under the
    // fields. Without this a screen reader user hears nothing at all and has no
    // way to tell a rejected sign-in from one that simply hasn't finished.
    final failure = widget.session.error;
    if (failure != null && failure != announcedError) {
      announcedError = failure;
      announceToScreenReader(context, failure);
    }
  }

  @override
  void dispose() {
    widget.session.removeListener(_onSessionChanged);
    email.dispose();
    password.dispose();
    emailField.focus.dispose();
    passwordField.focus.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (widget.session.loading) return;
    if (!validateAndFocusFirstError(context, formKey, [emailField, passwordField])) return;
    await widget.session.login(email.text, password.text);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    return Scaffold(
      body: Row(
        children: [
          if (MediaQuery.sizeOf(context).width >= 880)
            Expanded(
              child: Container(
                color: navy,
                // Marketing copy that repeats what the form already says, so it
                // is skipped rather than read out before the sign-in fields.
                child: ExcludeSemantics(
                  // The Spacers and 36px display text overflowed this panel at
                  // large text scale — the form half was already scrollable, this
                  // half was not.
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(Space.xxl + Space.xl),
                    child: ConstrainedBox(
                      constraints: BoxConstraints(
                        minHeight: MediaQuery.sizeOf(context).height - Space.xxl * 2 - Space.xl * 2,
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.workspace_premium_outlined, color: Colors.white, size: 34),
                              const SizedBox(width: Space.sm),
                              Text(
                                'CEU PORTAL',
                                style: theme.textTheme.titleMedium?.copyWith(color: Colors.white),
                              ),
                            ],
                          ),
                          const Spacer(),
                          Text(
                            'Compliance review,\nwithout the spreadsheet chase.',
                            style: theme.textTheme.displayLarge
                                ?.copyWith(color: Colors.white, height: 1.2),
                          ),
                          const SizedBox(height: Space.md + 2),
                          Text(
                            'Match attendance, tests, and surveys. Approve eligible attendees and deliver auditable certificates.',
                            style: theme.textTheme.bodyLarge
                                ?.copyWith(color: colors.onNavSubtle, height: 1.5),
                          ),
                          const Spacer(),
                          Text(
                            '7-year audit retention  •  Role-based access  •  Multi-format uploads',
                            style: theme.textTheme.bodyMedium?.copyWith(color: colors.onNavMuted),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          Expanded(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(Space.xxl - 4),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 430),
                  child: Form(
                    key: formKey,
                    child: AutofillGroup(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Heading(
                            child: Text(
                              'Sign in',
                              style: theme.textTheme.displaySmall?.copyWith(color: navy),
                            ),
                          ),
                          const SizedBox(height: Space.xs),
                          Text(
                            'Access your compliance workspace.',
                            style: theme.textTheme.bodyMedium
                                ?.copyWith(color: colors.textSecondary),
                          ),
                          const SizedBox(height: Space.xxl - 2),
                          TextFormField(
                            key: emailField.key,
                            focusNode: emailField.focus,
                            controller: email,
                            keyboardType: TextInputType.emailAddress,
                            textInputAction: TextInputAction.next,
                            autofillHints: const [AutofillHints.username],
                            decoration: const InputDecoration(labelText: 'Email address', prefixIcon: Icon(Icons.mail_outline)),
                            validator: emailValidator,
                          ),
                          const SizedBox(height: Space.md),
                          TextFormField(
                            key: passwordField.key,
                            focusNode: passwordField.focus,
                            controller: password,
                            obscureText: obscure,
                            textInputAction: TextInputAction.done,
                            autofillHints: const [AutofillHints.password],
                            onFieldSubmitted: (_) => submit(),
                            decoration: InputDecoration(
                              labelText: 'Password',
                              prefixIcon: const Icon(Icons.lock_outline),
                              suffixIcon: IconButton(
                                tooltip: obscure ? 'Show password' : 'Hide password',
                                onPressed: () => setState(() => obscure = !obscure),
                                icon: Icon(obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                              ),
                            ),
                            validator: (value) => value == null || value.isEmpty ? 'Enter your password' : null,
                          ),
                          if (widget.session.error != null) ...[
                            const SizedBox(height: Space.sm + 2),
                            FormErrorText(widget.session.error!),
                          ],
                          const SizedBox(height: Space.xl - 2),
                          ElevatedButton(
                            onPressed: widget.session.loading ? null : submit,
                            child: widget.session.loading
                                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                : const Text('Sign in'),
                          ),
                          const SizedBox(height: Space.md + 2),
                          Text(
                            'Forgot your password? Contact your NMEDA administrator.',
                            textAlign: TextAlign.center,
                            // Was blueGrey.shade500 at 4.37:1 on white — 13px
                            // body text that missed AA. textSecondary is 6.39:1.
                            style: theme.textTheme.bodySmall
                                ?.copyWith(color: colors.textSecondary),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
