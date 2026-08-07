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
      if (mounted) {
        final message = humanizeError(exception);
        setState(() => error = message);
        announceToScreenReader(context, message);
      }
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
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(humanizeError(exception))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) return ErrorPanel(message: error!, onRetry: load);
    if (users == null) return const LoadingPanel(label: 'Loading users');
    final currentId = widget.session.user!.id;
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxContentWidth),
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
              const SizedBox(height: Space.md + 2),
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
    final theme = Theme.of(context);
    final colors = theme.portal;
    final active = user['is_active'] as bool;
    final isAdmin = user['role'] == 'admin';
    final created = DateTime.tryParse(user['created_at']?.toString() ?? '');
    return ListTile(
      leading: ExcludeSemantics(
        child: CircleAvatar(
          backgroundColor: active ? colors.infoSurface : colors.neutralSurface,
          child: Icon(
            isAdmin ? Icons.shield_outlined : Icons.person_outline,
            // Was #98A2B3 at 2.58:1 — this icon is the only mark of an
            // inactive account on the row.
            color: active ? colors.info : colors.textTertiary,
          ),
        ),
      ),
      title: Text(
        user['full_name'] as String,
        style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
      ),
      subtitle: Text(
        created == null
            ? user['email'] as String
            : '${user['email']}  ·  added ${DateFormat.yMMMd().format(created)}',
      ),
      // Wrap, not Row: at large text scale two badges plus a menu button
      // overflowed the trailing slot.
      trailing: Wrap(
        spacing: Space.xs,
        runSpacing: Space.xxs,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          StatusBadge(isAdmin ? 'ADMIN' : 'PRESENTER', tone: isAdmin ? BadgeTone.info : BadgeTone.neutral),
          StatusBadge(active ? 'ACTIVE' : 'INACTIVE', tone: active ? BadgeTone.success : BadgeTone.danger),
          if (!isSelf)
            PopupMenuButton<String>(
              tooltip: 'Manage ${user['full_name']}',
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
  final nameField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'full name'));
  final emailField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'email'));
  final passwordField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'temporary password'));
  String role = 'presenter';
  bool saving = false;
  String? error;

  @override
  void dispose() {
    fullName.dispose();
    email.dispose();
    password.dispose();
    nameField.focus.dispose();
    emailField.focus.dispose();
    passwordField.focus.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    if (!validateAndFocusFirstError(context, formKey, [nameField, emailField, passwordField])) {
      return;
    }
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
      if (mounted) {
        setState(() => error = exception.message);
        announceToScreenReader(context, exception.message);
      }
    } catch (exception) {
      if (mounted) {
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
                key: nameField.key,
                focusNode: nameField.focus,
                controller: fullName,
                decoration: const InputDecoration(labelText: 'Full name'),
                validator: (value) => value == null || value.trim().length < 2 ? 'Enter a name' : null,
              ),
              const SizedBox(height: Space.sm + 2),
              TextFormField(
                key: emailField.key,
                focusNode: emailField.focus,
                controller: email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email'),
                validator: emailValidator,
              ),
              const SizedBox(height: Space.sm + 2),
              DropdownButtonFormField<String>(
                initialValue: role,
                decoration: const InputDecoration(labelText: 'Role'),
                items: const [
                  DropdownMenuItem(value: 'presenter', child: Text('Dealer / Presenter')),
                  DropdownMenuItem(value: 'admin', child: Text('Administrator')),
                ],
                onChanged: (value) => setState(() => role = value!),
              ),
              const SizedBox(height: Space.sm + 2),
              TextFormField(
                key: passwordField.key,
                focusNode: passwordField.focus,
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
                const SizedBox(height: Space.sm + 2),
                FormErrorText(error!),
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
