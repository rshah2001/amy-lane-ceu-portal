import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/api_client.dart';
import '../core/session.dart';
import '../widgets/common.dart';

class UsersPage extends StatefulWidget {
  const UsersPage({super.key, required this.session});
  final SessionController session;

  @override
  State<UsersPage> createState() => _UsersPageState();
}

class _UsersPageState extends State<UsersPage> {
  List<Map<String, dynamic>>? users;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() => error = null);
    try {
      final result = await widget.session.api.get('/users') as List;
      if (mounted) setState(() => users = result.cast<Map<String, dynamic>>());
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
  }

  Future<void> addUser() async {
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => _AddUserDialog(session: widget.session),
    );
    if (created == true) {
      await load();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('User created')));
      }
    }
  }

  Future<void> setActive(Map<String, dynamic> user, bool active) async {
    try {
      await widget.session.api.patch('/users/${user['id']}', {'is_active': active});
      await load();
    } catch (exception) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(exception.toString())));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) return ErrorPanel(message: error!, onRetry: load);
    if (users == null) return const LoadingPanel();
    final currentId = widget.session.user!.id;
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: 'Users',
                subtitle: 'Manage administrator and presenter accounts for the portal.',
                actions: [
                  ElevatedButton.icon(
                    onPressed: addUser,
                    icon: const Icon(Icons.person_add_alt_1),
                    label: const Text('Add user'),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              Card(
                child: Column(
                  children: [
                    for (var i = 0; i < users!.length; i++) ...[
                      if (i > 0) divider,
                      _UserRow(
                        user: users![i],
                        isSelf: users![i]['id'] == currentId,
                        onSetActive: (active) => setActive(users![i], active),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _UserRow extends StatelessWidget {
  const _UserRow({required this.user, required this.isSelf, required this.onSetActive});
  final Map<String, dynamic> user;
  final bool isSelf;
  final ValueChanged<bool> onSetActive;

  @override
  Widget build(BuildContext context) {
    final active = user['is_active'] as bool;
    final isAdmin = user['role'] == 'admin';
    final created = DateTime.tryParse(user['created_at']?.toString() ?? '');
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: active ? const Color(0xFFE9F2FA) : const Color(0xFFF0F2F5),
        child: Icon(
          isAdmin ? Icons.shield_outlined : Icons.person_outline,
          color: active ? const Color(0xFF245B85) : const Color(0xFF98A2B3),
        ),
      ),
      title: Text(user['full_name'] as String, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(
        created == null
            ? user['email'] as String
            : '${user['email']}  ·  added ${DateFormat.yMMMd().format(created)}',
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          StatusBadge(isAdmin ? 'ADMIN' : 'PRESENTER', tone: isAdmin ? BadgeTone.info : BadgeTone.neutral),
          const SizedBox(width: 8),
          StatusBadge(active ? 'ACTIVE' : 'INACTIVE', tone: active ? BadgeTone.success : BadgeTone.danger),
          if (!isSelf)
            PopupMenuButton<String>(
              tooltip: 'Manage',
              onSelected: (value) => onSetActive(value == 'activate'),
              itemBuilder: (context) => [
                if (active)
                  const PopupMenuItem(value: 'deactivate', child: Text('Deactivate'))
                else
                  const PopupMenuItem(value: 'activate', child: Text('Activate')),
              ],
            ),
        ],
      ),
    );
  }
}

class _AddUserDialog extends StatefulWidget {
  const _AddUserDialog({required this.session});
  final SessionController session;

  @override
  State<_AddUserDialog> createState() => _AddUserDialogState();
}

class _AddUserDialogState extends State<_AddUserDialog> {
  final formKey = GlobalKey<FormState>();
  final fullName = TextEditingController();
  final email = TextEditingController();
  final password = TextEditingController();
  String role = 'presenter';
  bool saving = false;
  String? error;

  @override
  void dispose() {
    fullName.dispose();
    email.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (!formKey.currentState!.validate()) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.session.api.post('/users', {
        'full_name': fullName.text.trim(),
        'email': email.text.trim(),
        'role': role,
        'password': password.text,
      });
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (exception) {
      if (mounted) setState(() => error = exception.message);
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add user'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Form(
          key: formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: fullName,
                decoration: const InputDecoration(labelText: 'Full name'),
                validator: (value) => value == null || value.trim().length < 2 ? 'Enter a name' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email'),
                validator: emailValidator,
              ),
              const SizedBox(height: 14),
              DropdownButtonFormField<String>(
                initialValue: role,
                decoration: const InputDecoration(labelText: 'Role'),
                items: const [
                  DropdownMenuItem(value: 'presenter', child: Text('Dealer / Presenter')),
                  DropdownMenuItem(value: 'admin', child: Text('Administrator')),
                ],
                onChanged: (value) => setState(() => role = value!),
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: password,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Temporary password',
                  helperText: 'At least 8 characters',
                ),
                validator: (value) =>
                    value == null || value.length < 8 ? 'At least 8 characters' : null,
              ),
              if (error != null) ...[
                const SizedBox(height: 14),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: saving ? null : () => Navigator.of(context).pop(false), child: const Text('Cancel')),
        ElevatedButton(
          onPressed: saving ? null : submit,
          child: saving
              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Text('Create user'),
        ),
      ],
    );
  }
}
