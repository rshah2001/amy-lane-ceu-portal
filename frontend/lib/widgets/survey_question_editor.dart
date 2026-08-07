import 'package:flutter/material.dart';

import 'common.dart';

/// Default options offered when a survey question is switched to multiple
/// choice — the agreement scale the client uses on her paper surveys.
const _agreementScale = [
  'Strongly Agree',
  'Agree',
  'Neither Agree or Disagree',
  'Disagree',
  'Strongly Disagree',
];

class SurveyQuestionDraft {
  SurveyQuestionDraft()
      : id = null,
        label = TextEditingController(),
        options = [];

  SurveyQuestionDraft.fromJson(Map<String, dynamic> json)
      : id = json['id']?.toString(),
        label = TextEditingController(text: json['label']?.toString() ?? ''),
        type = json['type']?.toString() == 'choice' ? 'choice' : 'text',
        options = [
          for (final option in (json['options'] as List?) ?? const []) TextEditingController(text: option.toString()),
        ];

  /// Original question id when editing, so past answers keyed by question id
  /// still line up. New questions get a positional id.
  final String? id;
  final TextEditingController label;

  /// 'text' = free-text box, 'choice' = pick one of [options].
  String type = 'text';
  final List<TextEditingController> options;

  void setType(String value) {
    type = value;
    if (type == 'choice' && options.isEmpty) {
      options.addAll([for (final option in _agreementScale) TextEditingController(text: option)]);
    }
  }

  Map<String, dynamic> toJson(String fallbackId) => {
        'id': id ?? fallbackId,
        'label': label.text.trim(),
        'type': type,
        if (type == 'choice')
          'options': [
            for (final option in options)
              if (option.text.trim().isNotEmpty) option.text.trim(),
          ],
      };

  void dispose() {
    label.dispose();
    for (final option in options) {
      option.dispose();
    }
  }
}

class SurveyQuestionEditor extends StatelessWidget {
  const SurveyQuestionEditor({
    super.key,
    required this.index,
    required this.draft,
    required this.onRemove,
    required this.onChanged,
  });

  final int index;
  final SurveyQuestionDraft draft;
  final VoidCallback onRemove;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).portal;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextFormField(
                controller: draft.label,
                decoration: InputDecoration(labelText: 'Survey question $index'),
                validator: (value) => value == null || value.trim().isEmpty ? 'Enter the question or remove it' : null,
              ),
            ),
            const SizedBox(width: Space.xs),
            SizedBox(
              width: 180,
              child: DropdownButtonFormField<String>(
                initialValue: draft.type,
                decoration: const InputDecoration(labelText: 'Answer type'),
                items: const [
                  DropdownMenuItem(value: 'text', child: Text('Written answer')),
                  DropdownMenuItem(value: 'choice', child: Text('Multiple choice')),
                ],
                onChanged: (value) {
                  draft.setType(value!);
                  onChanged();
                },
              ),
            ),
            const SizedBox(width: Space.xxs),
            IconButton(
              tooltip: 'Remove survey question $index',
              onPressed: onRemove,
              icon: const Icon(Icons.delete_outline, size: 20),
            ),
          ],
        ),
        if (draft.type == 'choice')
          Padding(
            padding: const EdgeInsets.only(left: Space.xl, top: Space.xs),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (var o = 0; o < draft.options.length; o++)
                  Row(
                    children: [
                      ExcludeSemantics(
                        child: Icon(Icons.radio_button_unchecked, size: 16, color: colors.textTertiary),
                      ),
                      const SizedBox(width: Space.xs),
                      Expanded(
                        child: TextFormField(
                          controller: draft.options[o],
                          decoration: InputDecoration(isDense: true, labelText: 'Option ${o + 1}'),
                          validator: (value) =>
                              o < 2 && (value == null || value.trim().isEmpty) ? 'At least two options required' : null,
                        ),
                      ),
                      IconButton(
                        tooltip: 'Remove option ${o + 1}',
                        onPressed: draft.options.length <= 2
                            ? null
                            : () {
                                draft.options.removeAt(o).dispose();
                                onChanged();
                              },
                        icon: const Icon(Icons.close, size: 16),
                      ),
                    ],
                  ),
                TextButton.icon(
                  onPressed: () {
                    draft.options.add(TextEditingController());
                    onChanged();
                  },
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Add option'),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
