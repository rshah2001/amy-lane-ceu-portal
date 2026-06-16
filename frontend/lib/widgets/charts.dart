import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../core/theme.dart';

/// A compact single-series bar chart with labelled categories on the x-axis.
class SimpleBarChart extends StatelessWidget {
  const SimpleBarChart({
    super.key,
    required this.labels,
    required this.values,
    this.color = navy,
    this.height = 220,
  });

  final List<String> labels;
  final List<double> values;
  final Color color;
  final double height;

  @override
  Widget build(BuildContext context) {
    final maxValue = values.isEmpty ? 0.0 : values.reduce((a, b) => a > b ? a : b);
    final top = maxValue <= 0 ? 1.0 : maxValue * 1.2;
    return SizedBox(
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
                const TextStyle(color: Colors.white, fontSize: 12),
              ),
            ),
          ),
          titlesData: FlTitlesData(
            topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 30)),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 34,
                getTitlesWidget: (value, meta) {
                  final index = value.toInt();
                  if (index < 0 || index >= labels.length) return const SizedBox.shrink();
                  return Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(labels[index], style: const TextStyle(fontSize: 11, color: Color(0xFF667085))),
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
                  BarChartRodData(toY: values[i], color: color, width: 22, borderRadius: BorderRadius.circular(4)),
                ],
              ),
          ],
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
            Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
            const SizedBox(height: 16),
            child,
          ],
        ),
      ),
    );
  }
}
