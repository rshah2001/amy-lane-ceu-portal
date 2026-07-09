import 'package:flutter/material.dart';

import '../core/session.dart';
import '../core/theme.dart';
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
  bool obscure = true;

  @override
  void initState() {
    super.initState();
    // Rebuild for loading/error changes triggered by the session controller.
    widget.session.addListener(_onSessionChanged);
  }

  void _onSessionChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.session.removeListener(_onSessionChanged);
    email.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (widget.session.loading) return;
    if (!formKey.currentState!.validate()) return;
    await widget.session.login(email.text, password.text);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          if (MediaQuery.sizeOf(context).width >= 880)
            Expanded(
              child: Container(
                color: navy,
                padding: const EdgeInsets.all(56),
                child: const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(Icons.workspace_premium_outlined, color: Colors.white, size: 34),
                        SizedBox(width: 12),
                        Text('CEU PORTAL', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700)),
                      ],
                    ),
                    Spacer(),
                    Text(
                      'Compliance review,\nwithout the spreadsheet chase.',
                      style: TextStyle(color: Colors.white, fontSize: 36, fontWeight: FontWeight.w700, height: 1.2),
                    ),
                    SizedBox(height: 18),
                    Text(
                      'Match attendance, tests, and surveys. Approve eligible attendees and deliver auditable certificates.',
                      style: TextStyle(color: Color(0xFFD6E2EC), fontSize: 17, height: 1.5),
                    ),
                    Spacer(),
                    Text('7-year audit retention  •  Role-based access  •  Multi-format uploads', style: TextStyle(color: Color(0xFFAAC0D1))),
                  ],
                ),
              ),
            ),
          Expanded(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(28),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 430),
                  child: Form(
                    key: formKey,
                    child: AutofillGroup(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const Text('Sign in', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700, color: navy)),
                          const SizedBox(height: 8),
                          Text('Access your compliance workspace.', style: TextStyle(color: Colors.blueGrey.shade600)),
                          const SizedBox(height: 30),
                          TextFormField(
                            controller: email,
                            keyboardType: TextInputType.emailAddress,
                            textInputAction: TextInputAction.next,
                            autofillHints: const [AutofillHints.username],
                            decoration: const InputDecoration(labelText: 'Email address', prefixIcon: Icon(Icons.mail_outline)),
                            validator: emailValidator,
                          ),
                          const SizedBox(height: 16),
                          TextFormField(
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
                            const SizedBox(height: 14),
                            Text(widget.session.error!, style: const TextStyle(color: Color(0xFFB42318))),
                          ],
                          const SizedBox(height: 22),
                          ElevatedButton(
                            onPressed: widget.session.loading ? null : submit,
                            child: widget.session.loading
                                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                : const Text('Sign in'),
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
