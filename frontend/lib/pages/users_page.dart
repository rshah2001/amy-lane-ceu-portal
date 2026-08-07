import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/session.dart';
import '../widgets/common.dart';
import '../widgets/portal_table.dart';

class UsersPage extends StatefulWidget {
  const UsersPage({super.key, required this.session});
  final SessionController session;

  @override
  State<UsersPage> createState() => _UsersPageState();
}

class _UsersPageState extends State<UsersPage> with LatestRequest {
  List<Map<String, dynamic>>? users;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    // Activating and deactivating both reload, and the menu can be worked
    // faster than the round trip: without the guard the older response repaints
    // the row as active again a moment after it was switched off.
    final request = beginRequest();
    setState(() => error = null);
    try {
      final result = await widget.session.api.get('/users') as List;
      if (request.isCurrent) setState(() => users = result.cast<Map<String, dynamic>>());
    } catch (exception) {
      if (request.isCurrent) _fail(exception);
    }
  }

  void _fail(Object exception) {
    if (!mounted) return;
    final message = humanizeError(exception);
    setState(() => error = message);
    announceToScreenReader(context, message);
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

  List<TableColumn<Map<String, dynamic>>> _columns(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final currentId = widget.session.user!.id;
    return [
      TableColumn<Map<String, dynamic>>(
        label: 'Name',
        width: 260,
        flex: 2,
        sortValue: (user) => user['full_name'] as String?,
        cell: (context, user) => Row(
          children: [
            ExcludeSemantics(
              child: CircleAvatar(
                radius: 16,
                backgroundColor: user['is_active'] == true
                    ? colors.infoSurface
                    : colors.neutralSurface,
                child: Icon(
                  user['role'] == 'admin' ? Icons.shield_outlined : Icons.person_outline,
                  size: 18,
                  // Was #98A2B3 at 2.58:1 — this icon is one of the marks of an
                  // inactive account on the row.
                  color: user['is_active'] == true ? colors.info : colors.textTertiary,
                ),
              ),
            ),
            const SizedBox(width: Space.xs),
            Flexible(
              child: Text(
                user['full_name'] as String,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              ),
            ),
          ],
        ),
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Email',
        width: 260,
        flex: 2,
        sortValue: (user) => user['email'] as String?,
        cell: (context, user) =>
            Text(user['email'] as String, overflow: TextOverflow.ellipsis),
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Role',
        width: 150,
        sortValue: (user) => user['role'] as String?,
        cell: (context, user) => StatusBadge(
          user['role'] == 'admin' ? 'ADMIN' : 'PRESENTER',
          tone: user['role'] == 'admin' ? BadgeTone.info : BadgeTone.neutral,
        ),
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Status',
        width: 140,
        // Sorting puts the deactivated accounts together, which is the only
        // reason anyone sorts this column.
        sortValue: (user) => user['is_active'] as bool?,
        cell: (context, user) => StatusBadge(
          user['is_active'] == true ? 'ACTIVE' : 'INACTIVE',
          tone: user['is_active'] == true ? BadgeTone.success : BadgeTone.danger,
        ),
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Added',
        width: 170,
        sortValue: (user) => DateTime.tryParse(user['created_at']?.toString() ?? ''),
        cell: (context, user) {
          final created = DateTime.tryParse(user['created_at']?.toString() ?? '');
          return Text(created == null ? '—' : formatDate(created));
        },
      ),
      TableColumn<Map<String, dynamic>>(
        label: 'Actions',
        width: 110,
        cell: (context, user) {
          // No self-service lockout: deactivating your own account would sign
          // you out of the only page that could undo it.
          if (user['id'] == currentId) return const SizedBox.shrink();
          final active = user['is_active'] as bool;
          return PopupMenuButton<String>(
            tooltip: 'Manage ${user['full_name']}',
            onSelected: (value) => setActive(user, value == 'activate'),
            itemBuilder: (context) => [
              if (active)
                const PopupMenuItem(value: 'deactivate', child: Text('Deactivate'))
              else
                const PopupMenuItem(value: 'activate', child: Text('Activate')),
            ],
          );
        },
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
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
              Expanded(
                child: Card(
                  child: PortalTable<Map<String, dynamic>>(
                    caption: 'Portal accounts',
                    columns: _columns(context),
                    rows: users,
                    error: error,
                    onRetry: load,
                    loadingLabel: 'Loading users',
                    emptyIcon: Icons.group_outlined,
                    emptyMessage: 'No accounts yet',
                    emptyDetail: 'Add an administrator or presenter to get started.',
                    // Paged. The account list is small today, but it only ever
                    // grows, and one shape for every table beats a special case
                    // that has to be revisited the first time it doesn't fit.
                    rowsPerPage: 25,
                    initialSortColumn: 0,
                    rowKey: (user) => user['id'] as Object,
                    rowSemanticLabel: (user) => user['full_name'] as String?,
                  ),
                ),
              ),
            ],
          ),
        ),
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
      // The server names the real problem here ("A user with that email
      // already exists"), which no generic wording can. It only falls back to
      // [humanizeError] when the failure arrived without a detail at all.
      if (mounted) {
        final message = exception.message.trim().isEmpty
            ? humanizeError(exception)
            : exception.message;
        setState(() => error = message);
        announceToScreenReader(context, message);
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
