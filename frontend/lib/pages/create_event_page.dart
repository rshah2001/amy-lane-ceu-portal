import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';

class CreateEventPage extends StatefulWidget {
  const CreateEventPage({super.key, required this.session, required this.onCreated});
  final SessionController session;
  final ValueChanged<TrainingEvent> onCreated;

  @override
  State<CreateEventPage> createState() => _CreateEventPageState();
}

class _CreateEventPageState extends State<CreateEventPage> {
  final formKey = GlobalKey<FormState>();
  final title = TextEditingController();
  final description = TextEditingController();
  final location = TextEditingController();
  final presenter = TextEditingController();
  final courseInstructor = TextEditingController();
  final hours = TextEditingController(text: '1.0');
  final postTestUrl = TextEditingController();
  final externalSurveyUrl = TextEditingController();
  final certificateTitle = TextEditingController(text: 'Certificate of Completion');
  String eventType = 'lunch_and_learn';
  String surveyMode = 'internal';
  bool surveyRequired = false;
  String testMode = 'external';
  final List<_QuestionDraft> testQuestions = [];
  DateTime date = DateTime.now().add(const Duration(days: 14));
  List<Map<String, dynamic>> presenters = [];
  int? assignedPresenterId;
  bool saving = false;
  String? error;

  @override
  void initState() {
    super.initState();
    loadPresenters();
  }

  Future<void> loadPresenters() async {
    try {
      final result = await widget.session.api.get('/users') as List;
      if (!mounted) return;
      setState(() {
        presenters = result
            .cast<Map<String, dynamic>>()
            .where((u) => u['role'] == 'presenter' && u['is_active'] == true)
            .toList();
      });
    } catch (_) {
      // Non-fatal: the event can still be created without an assignment.
    }
  }

  @override
  void dispose() {
    title.dispose();
    description.dispose();
    location.dispose();
    presenter.dispose();
    courseInstructor.dispose();
    hours.dispose();
    postTestUrl.dispose();
    externalSurveyUrl.dispose();
    certificateTitle.dispose();
    for (final question in testQuestions) {
      question.dispose();
    }
    super.dispose();
  }

  void addQuestion() {
    setState(() => testQuestions.add(_QuestionDraft()));
  }

  void removeQuestion(_QuestionDraft question) {
    setState(() {
      testQuestions.remove(question);
      question.dispose();
    });
  }

  Future<void> save() async {
    if (!formKey.currentState!.validate()) return;
    if (testMode == 'internal' && testQuestions.isEmpty) {
      setState(() => error = 'Add at least one test question or switch to an external post-test.');
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final json = await widget.session.api.post('/events', {
        'title': title.text.trim(),
        'description': description.text.trim().isEmpty ? null : description.text.trim(),
        'event_date': DateFormat('yyyy-MM-dd').format(date),
        'ceu_hours': double.parse(hours.text),
        'location': location.text.trim().isEmpty ? null : location.text.trim(),
        'presenter_name': presenter.text.trim().isEmpty ? null : presenter.text.trim(),
        'course_instructor': courseInstructor.text.trim().isEmpty ? null : courseInstructor.text.trim(),
        'event_type': eventType,
        'post_test_url': testMode == 'external' && postTestUrl.text.trim().isNotEmpty ? postTestUrl.text.trim() : null,
        'test_mode': testMode,
        'test_questions': testMode == 'internal'
            ? [for (var i = 0; i < testQuestions.length; i++) testQuestions[i].toJson('q${i + 1}')]
            : <Map<String, dynamic>>[],
        'survey_mode': surveyMode,
        'survey_required': surveyRequired,
        'external_survey_url': surveyMode == 'external' && externalSurveyUrl.text.trim().isNotEmpty
            ? externalSurveyUrl.text.trim()
            : null,
        'certificate_title': certificateTitle.text.trim(),
        'assigned_presenter_id': assignedPresenterId,
      }) as Map<String, dynamic>;
      widget.onCreated(TrainingEvent.fromJson(json));
    } catch (exception) {
      if (mounted) setState(() => error = exception.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 920),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const PageHeader(title: 'Create Event', subtitle: 'Set up the event record before uploading compliance documents.'),
              const SizedBox(height: 20),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Form(
                    key: formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextFormField(
                          controller: title,
                          decoration: const InputDecoration(labelText: 'Event title'),
                          validator: (value) => value == null || value.trim().length < 2 ? 'Enter an event title' : null,
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: description,
                          maxLines: 3,
                          decoration: const InputDecoration(labelText: 'Description'),
                        ),
                        const SizedBox(height: 16),
                        LayoutBuilder(
                          builder: (context, constraints) {
                            final fields = [
                              InkWell(
                                onTap: () async {
                                  final selected = await showDatePicker(
                                    context: context,
                                    firstDate: DateTime.now().subtract(const Duration(days: 365)),
                                    lastDate: DateTime.now().add(const Duration(days: 3650)),
                                    initialDate: date,
                                  );
                                  if (selected != null) setState(() => date = selected);
                                },
                                child: InputDecorator(
                                  decoration: const InputDecoration(labelText: 'Event date', prefixIcon: Icon(Icons.calendar_today_outlined)),
                                  child: Text(DateFormat.yMMMd().format(date)),
                                ),
                              ),
                              TextFormField(
                                controller: hours,
                                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                                decoration: const InputDecoration(labelText: 'CEU hours'),
                                validator: (value) => double.tryParse(value ?? '') == null ? 'Enter valid hours' : null,
                              ),
                            ];
                            if (constraints.maxWidth < 620) {
                              return Column(children: [fields[0], const SizedBox(height: 16), fields[1]]);
                            }
                            return Row(children: [Expanded(child: fields[0]), const SizedBox(width: 16), Expanded(child: fields[1])]);
                          },
                        ),
                        const SizedBox(height: 16),
                        TextFormField(controller: location, decoration: const InputDecoration(labelText: 'Location')),
                        const SizedBox(height: 16),
                        TextFormField(controller: presenter, decoration: const InputDecoration(labelText: 'Presenter name')),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: courseInstructor,
                          decoration: const InputDecoration(
                            labelText: 'Course instructor (prints on certificate)',
                            hintText: 'Defaults to the presenter if left blank',
                          ),
                        ),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<int?>(
                          initialValue: assignedPresenterId,
                          decoration: const InputDecoration(
                            labelText: 'Assign presenter (portal access)',
                            helperText: 'This presenter can sign in and upload the attendance sheet for this event',
                          ),
                          items: [
                            const DropdownMenuItem<int?>(value: null, child: Text('Unassigned')),
                            for (final p in presenters)
                              DropdownMenuItem<int?>(
                                value: p['id'] as int,
                                child: Text('${p['full_name']} (${p['email']})'),
                              ),
                          ],
                          onChanged: (value) => setState(() => assignedPresenterId = value),
                        ),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<String>(
                          initialValue: eventType,
                          decoration: const InputDecoration(labelText: 'Event type'),
                          items: const [
                            DropdownMenuItem(value: 'lunch_and_learn', child: Text('Lunch & Learn')),
                            DropdownMenuItem(value: 'webinar', child: Text('Webinar')),
                            DropdownMenuItem(value: 'workshop', child: Text('Workshop')),
                            DropdownMenuItem(value: 'conference', child: Text('Conference session')),
                          ],
                          onChanged: (value) => setState(() => eventType = value!),
                        ),
                        const SizedBox(height: 22),
                        const Align(alignment: Alignment.centerLeft, child: Text('Post-test', style: TextStyle(fontWeight: FontWeight.w700))),
                        const SizedBox(height: 8),
                        SegmentedButton<String>(
                          segments: const [
                            ButtonSegment(value: 'internal', label: Text('Built-in test'), icon: Icon(Icons.quiz_outlined)),
                            ButtonSegment(value: 'external', label: Text('External link'), icon: Icon(Icons.open_in_new)),
                          ],
                          selected: {testMode},
                          onSelectionChanged: (value) => setState(() => testMode = value.first),
                        ),
                        if (testMode == 'external') ...[
                          const SizedBox(height: 16),
                          TextFormField(
                            controller: postTestUrl,
                            keyboardType: TextInputType.url,
                            decoration: const InputDecoration(
                              labelText: 'External post-test link',
                              prefixIcon: Icon(Icons.link),
                              hintText: 'Google Forms or another testing system',
                            ),
                          ),
                        ] else ...[
                          const SizedBox(height: 12),
                          for (var i = 0; i < testQuestions.length; i++) ...[
                            _QuestionEditor(
                              index: i + 1,
                              draft: testQuestions[i],
                              onRemove: () => removeQuestion(testQuestions[i]),
                              onChanged: () => setState(() {}),
                            ),
                            const SizedBox(height: 12),
                          ],
                          Align(
                            alignment: Alignment.centerLeft,
                            child: OutlinedButton.icon(
                              onPressed: addQuestion,
                              icon: const Icon(Icons.add),
                              label: const Text('Add question'),
                            ),
                          ),
                        ],
                        const SizedBox(height: 22),
                        const Align(alignment: Alignment.centerLeft, child: Text('Feedback survey', style: TextStyle(fontWeight: FontWeight.w700))),
                        const SizedBox(height: 8),
                        SegmentedButton<String>(
                          segments: const [
                            ButtonSegment(value: 'internal', label: Text('Built-in survey'), icon: Icon(Icons.qr_code)),
                            ButtonSegment(value: 'external', label: Text('External survey'), icon: Icon(Icons.open_in_new)),
                          ],
                          selected: {surveyMode},
                          onSelectionChanged: (value) => setState(() => surveyMode = value.first),
                        ),
                        if (surveyMode == 'external') ...[
                          const SizedBox(height: 16),
                          TextFormField(
                            controller: externalSurveyUrl,
                            keyboardType: TextInputType.url,
                            decoration: const InputDecoration(labelText: 'External survey URL'),
                            validator: (value) => surveyMode == 'external' && (value == null || value.trim().isEmpty)
                                ? 'Enter the external survey URL'
                                : null,
                          ),
                        ],
                        const SizedBox(height: 8),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          value: surveyRequired,
                          onChanged: (value) => setState(() => surveyRequired = value),
                          title: const Text('Require survey to earn a certificate'),
                          subtitle: Text(
                            surveyRequired
                                ? 'Attendees must complete the feedback survey to be eligible.'
                                : 'Survey is optional (encouraged but does not block certificates).',
                            style: const TextStyle(fontSize: 12, color: Color(0xFF667085)),
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: certificateTitle,
                          decoration: const InputDecoration(labelText: 'Certificate heading'),
                          validator: (value) => value == null || value.trim().isEmpty ? 'Enter certificate wording' : null,
                        ),
                        if (error != null) ...[
                          const SizedBox(height: 14),
                          Text(error!, style: const TextStyle(color: Color(0xFFB42318))),
                        ],
                        const SizedBox(height: 24),
                        Align(
                          alignment: Alignment.centerRight,
                          child: ElevatedButton.icon(
                            onPressed: saving ? null : save,
                            icon: saving
                                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                : const Icon(Icons.save_outlined),
                            label: const Text('Create event'),
                          ),
                        ),
                      ],
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

class _QuestionDraft {
  _QuestionDraft()
      : prompt = TextEditingController(),
        choices = [TextEditingController(), TextEditingController(), TextEditingController(), TextEditingController()];

  final TextEditingController prompt;
  final List<TextEditingController> choices;
  int correctIndex = 0;

  Map<String, dynamic> toJson(String id) => {
        'id': id,
        'prompt': prompt.text.trim(),
        'choices': [for (final choice in choices) choice.text.trim()],
        'correct_index': correctIndex,
      };

  void dispose() {
    prompt.dispose();
    for (final choice in choices) {
      choice.dispose();
    }
  }
}

class _QuestionEditor extends StatelessWidget {
  const _QuestionEditor({
    required this.index,
    required this.draft,
    required this.onRemove,
    required this.onChanged,
  });

  final int index;
  final _QuestionDraft draft;
  final VoidCallback onRemove;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    return Card(
      color: const Color(0xFFF7FAFC),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Text('Question $index', style: const TextStyle(fontWeight: FontWeight.w700)),
                const Spacer(),
                IconButton(
                  tooltip: 'Remove question',
                  onPressed: onRemove,
                  icon: const Icon(Icons.delete_outline, size: 20),
                ),
              ],
            ),
            TextFormField(
              controller: draft.prompt,
              decoration: const InputDecoration(labelText: 'Question text'),
              validator: (value) => value == null || value.trim().isEmpty ? 'Enter the question' : null,
            ),
            const SizedBox(height: 6),
            const Align(
              alignment: Alignment.centerLeft,
              child: Text('Select the correct answer', style: TextStyle(fontSize: 12, color: Color(0xFF667085))),
            ),
            RadioGroup<int>(
              groupValue: draft.correctIndex,
              onChanged: (value) {
                draft.correctIndex = value!;
                onChanged();
              },
              child: Column(
                children: [
                  for (var c = 0; c < draft.choices.length; c++)
                    Row(
                      children: [
                        Radio<int>(value: c),
                        Expanded(
                          child: TextFormField(
                            controller: draft.choices[c],
                            decoration: InputDecoration(labelText: 'Choice ${c + 1}'),
                            validator: (value) =>
                                c < 2 && (value == null || value.trim().isEmpty) ? 'Required' : null,
                          ),
                        ),
                      ],
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
