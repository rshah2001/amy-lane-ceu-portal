import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import 'common.dart';

/// A compact single-series bar chart with labelled categories on the x-axis.
class SimpleBarChart extends StatelessWidget {
  const SimpleBarChart({
    super.key,
    required this.labels,
    required this.values,
    required this.description,
    this.color = navy,
    this.height = 220,
  });

  final List<String> labels;
  final List<double> values;
  final Color color;
  final double height;

  /// What the chart is showing, e.g. `'Post-test score distribution'`. Used to
  /// open the spoken text equivalent.
  final String description;

  /// The chart read out loud.
  ///
  /// `fl_chart` paints to a canvas and exposes its values only on hover, so
  /// without this the three dashboard charts are simply absent for anyone using
  /// a screen reader, and unreachable for anyone who cannot use a mouse. The
  /// numbers are the point of the chart, so they are stated in full rather than
  /// summarised.
  String get _spokenEquivalent {
    if (values.isEmpty) return '$description: no data yet.';
    final pairs = [
      for (var i = 0; i < values.length; i++)
        '${i < labels.length ? labels[i] : 'Item ${i + 1}'}: ${values[i].toInt()}',
    ];
    return '$description. Bar chart with ${values.length} '
        '${values.length == 1 ? 'bar' : 'bars'}. ${pairs.join(', ')}.';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.portal;
    final maxValue = values.isEmpty ? 0.0 : values.reduce((a, b) => a > b ? a : b);
    final top = maxValue <= 0 ? 1.0 : maxValue * 1.2;
    return Semantics(
      label: _spokenEquivalent,
      // The painted canvas has nothing meaningful under it, so the label above
      // replaces it wholesale rather than competing with it.
      excludeSemantics: true,
      child: SizedBox(
        height: height,
        child: BarChart(
          BarChartData(
            alignment: BarChartAlignment.spaceAround,
            maxY: top,
            borderData: FlBorderData(show: false),
            gridData: const FlGridData(show: true, drawVerticalLine: false),
            barTouchData: BarTouchData(
              touchTooltipData: BarTouchTooltipData(
                getTooltipItem: (group, _, rod, __) => BarTooltipItem(
                  '${labels[group.x]}\n${rod.toY.toInt()}',
                  theme.textTheme.labelMedium!.copyWith(color: Colors.white),
                ),
              ),
            ),
            titlesData: FlTitlesData(
              topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
              leftTitles: const AxisTitles(
                sideTitles: SideTitles(showTitles: true, reservedSize: 30),
              ),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 34,
                  getTitlesWidget: (value, meta) {
                    final index = value.toInt();
                    if (index < 0 || index >= labels.length) return const SizedBox.shrink();
                    return Padding(
                      padding: const EdgeInsets.only(top: Space.xxs + 2),
                      child: Text(
                        labels[index],
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: colors.textTertiary,
                          fontWeight: FontWeight.w400,
                        ),
                      ),
                    );
                  },
                ),
              ),
            ),
            barGroups: [
              for (var i = 0; i < values.length; i++)
                BarChartGroupData(
                  x: i,
                  barRods: [
                    BarChartRodData(
                      toY: values[i],
                      color: color,
                      width: 22,
                      borderRadius: BorderRadius.circular(Radii.sm),
                    ),
                  ],
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Card wrapper giving a chart a title and padding.
class ChartCard extends StatelessWidget {
  const ChartCard({super.key, required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionTitle(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: Space.md),
            child,
          ],
        ),
      ),
    );
  }
}
