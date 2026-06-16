import 'package:flutter/material.dart';

import '../core/session.dart';
import '../core/theme.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key, required this.session});
  final SessionController session;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final email = TextEditingController(text: 'admin@example.com');
  final password = TextEditingController(text: 'Admin123!');
  bool obscure = true;

  @override
  void dispose() {
    email.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit() async {
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
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text('Sign in', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700, color: navy)),
                      const SizedBox(height: 8),
                      Text('Access your compliance workspace.', style: TextStyle(color: Colors.blueGrey.shade600)),
                      const SizedBox(height: 30),
                      TextField(
                        controller: email,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(labelText: 'Email address', prefixIcon: Icon(Icons.mail_outline)),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: password,
                        obscureText: obscure,
                        onSubmitted: (_) => submit(),
                        decoration: InputDecoration(
                          labelText: 'Password',
                          prefixIcon: const Icon(Icons.lock_outline),
                          suffixIcon: IconButton(
                            tooltip: obscure ? 'Show password' : 'Hide password',
                            onPressed: () => setState(() => obscure = !obscure),
                            icon: Icon(obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                          ),
                        ),
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
                      const SizedBox(height: 18),
                      const Text(
                        'Seed access: admin@example.com / Admin123!',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: 12, color: Color(0xFF667085)),
                      ),
                    ],
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
