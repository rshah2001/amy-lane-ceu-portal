import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../widgets/common.dart';

class AttendeeSearchPage extends StatefulWidget {
  const AttendeeSearchPage({super.key, required this.session});
  final SessionController session;

  @override
  State<AttendeeSearchPage> createState() => _AttendeeSearchPageState();
}

class _AttendeeSearchPageState extends State<AttendeeSearchPage> {
  final query = TextEditingController();
  List<Map<String, dynamic>>? rows;
  String? error;

  @override
  void initState() {
    super.initState();
    search();
  }

  @override
  void dispose() {
    query.dispose();
    super.dispose();
  }

  Future<void> search() async {
    try {
      final encoded = Uri.encodeQueryComponent(query.text.trim());
      final result = await widget.session.api.get('/attendees/search${encoded.isEmpty ? '' : '?q=$encoded'}') as List;
      if (mounted) {
        setState(() {
          rows = result.cast<Map<String, dynamic>>();
          error = null;
        });
      }
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    }
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
              const PageHeader(title: 'Attendee Search', subtitle: 'Find attendees across events, approvals, and issued certificates.'),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(child: TextField(controller: query, onSubmitted: (_) => search(), decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search name, email, or company'))),
                  const SizedBox(width: 10),
                  IconButton.filledTonal(tooltip: 'Search', onPressed: search, icon: const Icon(Icons.search)),
                ],
              ),
              if (error != null) ...[
                const SizedBox(height: 10),
                Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
              ],
              const SizedBox(height: 14),
              Expanded(
                child: Card(
                  child: rows == null
                      ? const LoadingPanel()
                      : SingleChildScrollView(
                          child: SingleChildScrollView(
                            scrollDirection: Axis.horizontal,
                            child: DataTable(
                              columns: const [
                                DataColumn(label: Text('Attendee')),
                                DataColumn(label: Text('Email')),
                                DataColumn(label: Text('Company')),
                                DataColumn(label: Text('Event')),
                                DataColumn(label: Text('Date')),
                                DataColumn(label: Text('Status')),
                                DataColumn(label: Text('Certificate')),
                              ],
                              rows: rows!
                                  .map(
                                    (row) => DataRow(
                                      cells: [
                                        DataCell(SizedBox(width: 190, child: Text(row['full_name'] as String, style: const TextStyle(fontWeight: FontWeight.w600)))),
                                        DataCell(Text(row['email'] as String? ?? '')),
                                        DataCell(Text(row['company'] as String? ?? '')),
                                        DataCell(SizedBox(width: 240, child: Text(row['event_title'] as String))),
                                        DataCell(Text(DateFormat.yMMMd().format(DateTime.parse(row['event_date'] as String)))),
                                        DataCell(StatusBadge(row['approved'] == true ? 'APPROVED' : row['eligible'] == true ? 'ELIGIBLE' : 'INELIGIBLE', tone: row['approved'] == true || row['eligible'] == true ? BadgeTone.success : BadgeTone.danger)),
                                        DataCell(Text(row['certificate_number'] as String? ?? '')),
                                      ],
                                    ),
                                  )
                                  .toList(),
                            ),
                          ),
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

