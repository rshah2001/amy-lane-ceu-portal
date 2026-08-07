import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../core/session.dart';
import '../models/models.dart';
import '../widgets/common.dart';
import '../widgets/survey_question_editor.dart';

class CreateEventPage extends StatefulWidget {
  const CreateEventPage({super.key, required this.session, required this.onSaved, this.event});
  final SessionController session;

  /// When set, the page edits this existing event instead of creating one.
  final TrainingEvent? event;
  final ValueChanged<TrainingEvent> onSaved;

  @override
  State<CreateEventPage> createState() => _CreateEventPageState();
}

class _CreateEventPageState extends State<CreateEventPage> {
  final formKey = GlobalKey<FormState>();
  final title = TextEditingController();
  final titleFocus = FocusNode();
  final description = TextEditingController();
  final location = TextEditingController();
  final locationFocus = FocusNode();
  final presenter = TextEditingController();
  final hours = TextEditingController(text: '1.0');
  final postTestUrl = TextEditingController();
  final externalSurveyUrl = TextEditingController();
  final certificateTitle = TextEditingController(text: 'Certificate of Completion');
  // Keys + focus nodes for the named fields, in visual order, so a failed
  // validation on this ~15-field page lands the caret on the actual problem
  // rather than leaving it on the save button 800px below it.
  final titleField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'event title'));
  final hoursField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'CEU hours'));
  final postTestUrlField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'external post-test link'));
  final externalSurveyUrlField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'external survey URL'));
  final certificateTitleField = (key: GlobalKey<FormFieldState<String>>(), focus: FocusNode(debugLabel: 'certificate heading'));
  String eventType = 'lunch_and_learn';
  String surveyMode = 'internal';
  bool surveyRequired = false;
  String testMode = 'external';
  final List<_QuestionDraft> testQuestions = [];
  final List<SurveyQuestionDraft> surveyQuestions = [];
  DateTime date = DateTime.now().add(const Duration(days: 14));
  List<Map<String, dynamic>> presenters = [];
  int? assignedPresenterId;
  bool saving = false;
  String? error;

  bool get isEdit => widget.event != null;

  @override
  void initState() {
    super.initState();
    final event = widget.event;
    if (event != null) _prefill(event);
    loadPresenters();
  }

  void _prefill(TrainingEvent event) {
    title.text = event.title;
    description.text = event.description ?? '';
    location.text = event.location ?? '';
    presenter.text = event.presenterName ?? '';
    hours.text = event.ceuHours.toStringAsFixed(1);
    postTestUrl.text = event.postTestUrl ?? '';
    externalSurveyUrl.text = event.externalSurveyUrl ?? '';
    certificateTitle.text = event.certificateTitle;
    eventType = event.eventType;
    surveyMode = event.surveyMode;
    surveyRequired = event.surveyRequired;
    testMode = event.testMode;
    date = event.eventDate;
    assignedPresenterId = event.assignedPresenterId;
    for (final question in event.testQuestions) {
      testQuestions.add(_QuestionDraft.fromJson(question));
    }
    for (final question in event.surveyQuestions) {
      surveyQuestions.add(SurveyQuestionDraft.fromJson(question));
    }
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
      // Non-fatal: the event can still be saved without an assignment.
    }
  }

  @override
  void dispose() {
    title.dispose();
    titleFocus.dispose();
    description.dispose();
    location.dispose();
    locationFocus.dispose();
    presenter.dispose();
    hours.dispose();
    postTestUrl.dispose();
    externalSurveyUrl.dispose();
    certificateTitle.dispose();
    titleField.focus.dispose();
    hoursField.focus.dispose();
    postTestUrlField.focus.dispose();
    externalSurveyUrlField.focus.dispose();
    certificateTitleField.focus.dispose();
    for (final question in testQuestions) {
      question.dispose();
    }
    for (final question in surveyQuestions) {
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

  void addSurveyQuestion() {
    setState(() => surveyQuestions.add(SurveyQuestionDraft()));
  }

  void removeSurveyQuestion(SurveyQuestionDraft question) {
    setState(() {
      surveyQuestions.remove(question);
      question.dispose();
    });
  }

  Future<void> save() async {
    final ordered = [
      titleField,
      hoursField,
      if (testMode == 'external') postTestUrlField,
      if (surveyMode == 'external') externalSurveyUrlField,
      certificateTitleField,
    ];
    if (!validateAndFocusFirstError(context, formKey, ordered)) return;
    if (testMode == 'internal' && testQuestions.isEmpty) {
      const message = 'Add at least one test question or switch to an external post-test.';
      setState(() => error = message);
      announceToScreenReader(context, message);
      return;
    }
    if (testMode == 'internal') {
      // A wrong answer key is worse than an incomplete form: the event saves,
      // the test runs, and attendees who answered correctly are failed.
      final unanswered = [
        for (var i = 0; i < testQuestions.length; i++)
          if (!testQuestions[i].hasAnswer) i + 1,
      ];
      if (unanswered.isNotEmpty) {
        final message = unanswered.length == 1
            ? 'Question ${unanswered.first} has no correct answer marked. '
                'Select the correct choice before saving.'
            : 'Questions ${unanswered.join(', ')} have no correct answer marked. '
                'Select the correct choice for each before saving.';
        setState(() => error = message);
        announceToScreenReader(context, message);
        return;
      }
    }
    setState(() {
      saving = true;
      error = null;
    });
    final body = <String, dynamic>{
      'title': title.text.trim(),
      'description': description.text.trim().isEmpty ? null : description.text.trim(),
      'event_date': DateFormat('yyyy-MM-dd').format(date),
      'ceu_hours': double.parse(hours.text),
      'location': location.text.trim().isEmpty ? null : location.text.trim(),
      'presenter_name': presenter.text.trim().isEmpty ? null : presenter.text.trim(),
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
      // Only sent when editing: the create flow lets the server seed its
      // default survey questions. An empty list is omitted so the PUT never
      // wipes the server-side questions by accident.
      if (isEdit && surveyMode == 'internal' && surveyQuestions.isNotEmpty)
        'survey_questions': [for (var i = 0; i < surveyQuestions.length; i++) surveyQuestions[i].toJson('s${i + 1}')],
    };
    try {
      final json = isEdit
          ? await widget.session.api.put('/events/${widget.event!.id}', body)
          : await widget.session.api.post('/events', body);
      widget.onSaved(TrainingEvent.fromJson(json as Map<String, dynamic>));
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

  /// Nudge shown under the portal-access dropdown.
  ///
  /// The failure this exists to stop is quiet: the event saves fine, and only
  /// weeks later does the presenter discover they can't sign in to upload
  /// anything. So when the typed certificate name matches a real portal
  /// account that hasn't been given access, offer it in one click; and when
  /// nobody is assigned at all, say plainly who is left holding the upload.
  List<Widget> _presenterAccessHint() {
    if (assignedPresenterId != null) return const [];
    final colors = Theme.of(context).portal;
    final typed = presenter.text.trim().toLowerCase();
    Map<String, dynamic>? match;
    if (typed.isNotEmpty) {
      for (final candidate in presenters) {
        if ((candidate['full_name'] as String?)?.trim().toLowerCase() == typed) {
          match = candidate;
          break;
        }
      }
    }
    return [
      const SizedBox(height: Space.xs),
      Container(
        width: double.infinity,
        padding: const EdgeInsets.all(Space.sm),
        decoration: BoxDecoration(
          color: colors.warningSurface,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: colors.warning),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(Icons.info_outline, size: 18, color: colors.warning),
            const SizedBox(width: Space.xs),
            Expanded(
              child: match == null
                  ? Text(
                      'Nobody can sign in to upload the sign-in sheet for this event. '
                      'An administrator will have to upload it instead.',
                      style: Theme.of(context).textTheme.bodySmall,
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${match['full_name']} has a portal account but no access to this event.',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        const SizedBox(height: Space.xxs),
                        TextButton(
                          onPressed: () => setState(() => assignedPresenterId = match!['id'] as int),
                          child: Text('Give ${match['full_name']} access'),
                        ),
                      ],
                    ),
            ),
          ],
        ),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: pagePadding,
      child: Center(
        // The page column matches every other page in the shell so it stops
        // resizing on navigation; the form itself keeps a readable measure.
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: maxFormWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PageHeader(
                title: isEdit ? 'Edit Event' : 'Create Event',
                subtitle: isEdit
                    ? 'Update event details, post-test questions, and survey settings.'
                    : 'Set up the event record before uploading compliance documents.',
              ),
              const SizedBox(height: 20),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Form(
                    key: formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _SuggestTextField(
                          controller: title,
                          focusNode: titleFocus,
                          fieldKey: titleField.key,
                          label: 'Event title',
                          suggestion: 'CAMS Lunch & Learn',
                          validator: (value) => value == null || value.trim().length < 2 ? 'Enter an event title' : null,
                        ),
                        const SizedBox(height: Space.md),
                        TextFormField(
                          controller: description,
                          maxLines: 3,
                          decoration: const InputDecoration(labelText: 'Description'),
                        ),
                        const SizedBox(height: 16),
                        LayoutBuilder(
                          builder: (context, constraints) {
                            final fields = [
                              Semantics(
                                button: true,
                                label: 'Event date, ${DateFormat.yMMMd().format(date)}. '
                                    'Opens a date picker.',
                                excludeSemantics: true,
                                child: InkWell(
                                  onTap: () async {
                                    final earliest = DateTime.now().subtract(const Duration(days: 365));
                                    final selected = await showDatePicker(
                                      context: context,
                                      firstDate: date.isBefore(earliest) ? date : earliest,
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
                              ),
                              TextFormField(
                                key: hoursField.key,
                                focusNode: hoursField.focus,
                                controller: hours,
                                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                                decoration: const InputDecoration(labelText: 'CEU hours'),
                                validator: (value) {
                                  final parsed = double.tryParse(value?.trim() ?? '');
                                  if (parsed == null) return 'Enter valid hours';
                                  if (parsed <= 0) return 'Hours must be greater than zero';
                                  return null;
                                },
                              ),
                            ];
                            if (constraints.maxWidth < 620) {
                              return Column(children: [fields[0], const SizedBox(height: 16), fields[1]]);
                            }
                            return Row(children: [Expanded(child: fields[0]), const SizedBox(width: 16), Expanded(child: fields[1])]);
                          },
                        ),
                        const SizedBox(height: 16),
                        _SuggestTextField(
                          controller: location,
                          focusNode: locationFocus,
                          label: 'Location',
                          suggestion: 'Live Virtual',
                        ),
                        const SizedBox(height: 16),
                        // These two fields both used to say "presenter" and sat
                        // next to each other, which read as one question asked
                        // twice. Admins filled the certificate name and left the
                        // access dropdown on "Unassigned" — 23 of 24 live events
                        // ended up with no presenter able to sign in. They are
                        // now explicitly framed as two different questions.
                        const Align(alignment: Alignment.centerLeft, child: SectionTitle('Who is teaching this event')),
                        const SizedBox(height: Space.xs),
                        TextFormField(
                          controller: presenter,
                          decoration: const InputDecoration(
                            labelText: 'Presenter name — printed on the certificate',
                            helperText: "Exactly as it should appear on the certificate. For two presenters, separate with ' & '",
                          ),
                          // Rebuild so the suggestion below can react as they type.
                          onChanged: (_) => setState(() {}),
                        ),
                        const SizedBox(height: 16),
                        DropdownButtonFormField<int?>(
                          initialValue: assignedPresenterId,
                          decoration: const InputDecoration(
                            labelText: 'Portal access — who can upload the sign-in sheet',
                            helperText: 'A different question from the name above: this is the account that can sign in for this event',
                          ),
                          items: [
                            const DropdownMenuItem<int?>(value: null, child: Text('Nobody (admins upload it)')),
                            for (final p in presenters)
                              DropdownMenuItem<int?>(
                                value: p['id'] as int,
                                child: Text('${p['full_name']} (${p['email']})'),
                              ),
                          ],
                          onChanged: (value) => setState(() => assignedPresenterId = value),
                        ),
                        ..._presenterAccessHint(),
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
                        const Align(alignment: Alignment.centerLeft, child: SectionTitle('Post-test')),
                        const SizedBox(height: Space.xs),
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
                            key: postTestUrlField.key,
                            focusNode: postTestUrlField.focus,
                            controller: postTestUrl,
                            keyboardType: TextInputType.url,
                            decoration: const InputDecoration(
                              labelText: 'External post-test link',
                              prefixIcon: Icon(Icons.link),
                              hintText: 'Google Forms or another testing system',
                            ),
                            validator: (value) => testMode == 'external' ? optionalUrlValidator(value) : null,
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
                        const Align(alignment: Alignment.centerLeft, child: SectionTitle('Feedback survey')),
                        const SizedBox(height: Space.xs),
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
                            key: externalSurveyUrlField.key,
                            focusNode: externalSurveyUrlField.focus,
                            controller: externalSurveyUrl,
                            keyboardType: TextInputType.url,
                            decoration: const InputDecoration(labelText: 'External survey URL'),
                            validator: (value) {
                              if (surveyMode != 'external') return null;
                              if (value == null || value.trim().isEmpty) return 'Enter the external survey URL';
                              return optionalUrlValidator(value);
                            },
                          ),
                        ] else if (isEdit) ...[
                          const SizedBox(height: 12),
                          Align(
                            alignment: Alignment.centerLeft,
                            child: Text(
                              'Survey questions attendees are asked. Edits replace the current list. '
                              'Switch a question to "Multiple choice" for an agree/disagree scale — the standard scale is pre-filled.',
                              style: theme.textTheme.labelMedium?.copyWith(
                                color: theme.portal.textSecondary,
                                fontWeight: FontWeight.w400,
                              ),
                            ),
                          ),
                          const SizedBox(height: 10),
                          for (var i = 0; i < surveyQuestions.length; i++) ...[
                            SurveyQuestionEditor(
                              index: i + 1,
                              draft: surveyQuestions[i],
                              onRemove: () => removeSurveyQuestion(surveyQuestions[i]),
                              onChanged: () => setState(() {}),
                            ),
                            const SizedBox(height: 10),
                          ],
                          Align(
                            alignment: Alignment.centerLeft,
                            child: OutlinedButton.icon(
                              onPressed: addSurveyQuestion,
                              icon: const Icon(Icons.add),
                              label: const Text('Add survey question'),
                            ),
                          ),
                        ],
                        const SizedBox(height: 8),
                        _SurveyRequiredToggle(
                          value: surveyRequired,
                          onChanged: (value) => setState(() => surveyRequired = value),
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          key: certificateTitleField.key,
                          focusNode: certificateTitleField.focus,
                          controller: certificateTitle,
                          decoration: const InputDecoration(labelText: 'Certificate heading'),
                          validator: (value) => value == null || value.trim().isEmpty ? 'Enter certificate wording' : null,
                        ),
                        if (error != null) ...[
                          const SizedBox(height: Space.sm + 2),
                          FormErrorText(error!),
                        ],
                        const SizedBox(height: Space.xl),
                        Align(
                          alignment: Alignment.centerRight,
                          child: ElevatedButton.icon(
                            onPressed: saving ? null : save,
                            icon: saving
                                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                : const Icon(Icons.save_outlined),
                            label: Text(isEdit ? 'Save changes' : 'Create event'),
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

/// Free-text field that also offers a canned suggestion (combo-box style) for
/// the values the client reuses on nearly every event.
class _SuggestTextField extends StatelessWidget {
  const _SuggestTextField({
    required this.controller,
    required this.focusNode,
    required this.label,
    required this.suggestion,
    this.fieldKey,
    this.validator,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final String label;
  final String suggestion;

  /// Forwarded to the inner [TextFormField] so failed validation can find and
  /// focus this field.
  final GlobalKey<FormFieldState<String>>? fieldKey;
  final String? Function(String?)? validator;

  @override
  Widget build(BuildContext context) {
    return RawAutocomplete<String>(
      textEditingController: controller,
      focusNode: focusNode,
      optionsBuilder: (value) {
        final text = value.text.trim().toLowerCase();
        // Hide the popup once the suggestion is already typed exactly.
        if (text == suggestion.toLowerCase()) return const Iterable<String>.empty();
        if (text.isEmpty || suggestion.toLowerCase().contains(text)) return <String>[suggestion];
        return const Iterable<String>.empty();
      },
      fieldViewBuilder: (context, textController, fieldFocusNode, onFieldSubmitted) => TextFormField(
        key: fieldKey,
        controller: textController,
        focusNode: fieldFocusNode,
        decoration: InputDecoration(labelText: label, suffixIcon: const Icon(Icons.arrow_drop_down)),
        validator: validator,
        onFieldSubmitted: (_) => onFieldSubmitted(),
      ),
      optionsViewBuilder: (context, onSelected, options) => Align(
        alignment: Alignment.topLeft,
        child: Material(
          elevation: 4,
          borderRadius: BorderRadius.circular(8),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 360),
            child: ListView(
              shrinkWrap: true,
              padding: EdgeInsets.zero,
              children: [
                for (final option in options)
                  ListTile(
                    dense: true,
                    leading: const Icon(Icons.star_outline, size: 18),
                    title: Text(option),
                    onTap: () => onSelected(option),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Survey requirement switch with an unmistakable written state, so on/off is
/// never ambiguous: green "Required" pill when on, red-tinted "Optional" when off.
class _SurveyRequiredToggle extends StatelessWidget {
  const _SurveyRequiredToggle({required this.value, required this.onChanged});
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        // The track colour now comes from switchTheme.
        Switch(value: value, onChanged: onChanged),
        const SizedBox(width: Space.xs + 2),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Require survey to earn a certificate'),
              const SizedBox(height: 2),
              Text(
                value
                    ? 'Attendees must complete the feedback survey to be eligible.'
                    : 'Survey is optional (encouraged but does not block certificates).',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: theme.portal.textSecondary,
                  fontWeight: FontWeight.w400,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: Space.xs + 2),
        StatusBadge(
          value ? 'Required' : 'Optional',
          // "Optional" is a valid configuration, not a fault. Red read as
          // "something is wrong here" on a setting that is off by default.
          tone: value ? BadgeTone.success : BadgeTone.neutral,
        ),
      ],
    );
  }
}

class _QuestionDraft {
  _QuestionDraft()
      : id = null,
        prompt = TextEditingController(),
        choices = [TextEditingController(), TextEditingController(), TextEditingController(), TextEditingController()];

  _QuestionDraft.fromJson(Map<String, dynamic> json)
      : id = json['id']?.toString(),
        prompt = TextEditingController(text: json['prompt']?.toString() ?? ''),
        choices = [
          for (final choice in (json['choices'] as List?) ?? const []) TextEditingController(text: choice.toString()),
        ],
        correctIndex = json['correct_index'] as int? ?? 0 {
    while (choices.length < 4) {
      choices.add(TextEditingController());
    }
    // An existing question always has an answer; only guard the stored index
    // against a choice list that has since shrunk.
    if (correctIndex != null && correctIndex! >= choices.length) correctIndex = 0;
  }

  /// Original question id when editing, so existing test submissions keep
  /// pointing at the same question. New questions get a positional id.
  final String? id;
  final TextEditingController prompt;
  final List<TextEditingController> choices;

  /// Null until someone actually picks the answer.
  ///
  /// This used to default to 0, which is indistinguishable from deliberately
  /// choosing the first option — so an author who filled in a question and
  /// forgot the radio silently shipped "A" as the answer key. Every attendee
  /// who answered correctly was then marked wrong, on a test that decides CEU
  /// credit. Unanswered is now its own state and is refused at save.
  int? correctIndex;

  bool get hasAnswer => correctIndex != null;

  Map<String, dynamic> toJson(String fallbackId) => {
        'id': id ?? fallbackId,
        'prompt': prompt.text.trim(),
        'choices': [for (final choice in choices) choice.text.trim()],
        // Guarded by the save-time check; the ?? 0 only keeps the type honest.
        'correct_index': correctIndex ?? 0,
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
    final theme = Theme.of(context);
    return Card(
      color: theme.portal.surfaceSubtle,
      child: Padding(
        padding: const EdgeInsets.all(Space.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                SectionTitle(
                  'Question $index',
                  style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
                const Spacer(),
                IconButton(
                  tooltip: 'Remove question $index',
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
            const SizedBox(height: Space.xxs + 2),
            Align(
              alignment: Alignment.centerLeft,
              // Flagged in place, while the author is looking at the question,
              // rather than only at save. Nothing about an unmarked question
              // looks wrong otherwise — the radios simply sit empty.
              child: Text(
                draft.hasAnswer ? 'Select the correct answer' : 'Select the correct answer — none marked yet',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: draft.hasAnswer ? theme.portal.textSecondary : theme.portal.warning,
                  fontWeight: draft.hasAnswer ? FontWeight.w400 : FontWeight.w600,
                ),
              ),
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
                        // The radio sits beside a text field rather than a
                        // label, so on its own it announced as "radio button,
                        // 1 of 4" with no name — the "Select the correct
                        // answer" hint above is a detached node.
                        Semantics(
                          label: 'Mark choice ${c + 1} as the correct answer',
                          child: Radio<int>(value: c),
                        ),
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
