import 'package:flutter/material.dart';

const navy = Color(0xFF17324D);
const teal = Color(0xFF177E89);
const gold = Color(0xFFB58A3B);
const canvas = Color(0xFFF5F7FA);
const border = Color(0xFFDCE3EA);

ThemeData buildPortalTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: navy,
    brightness: Brightness.light,
    primary: navy,
    secondary: teal,
    surface: Colors.white,
    error: const Color(0xFFB42318),
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: canvas,
    fontFamily: 'Arial',
    cardTheme: const CardThemeData(
      color: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(8)),
        side: BorderSide(color: border),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(6)),
        borderSide: BorderSide(color: border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(6)),
        borderSide: BorderSide(color: border),
      ),
      contentPadding: EdgeInsets.symmetric(horizontal: 14, vertical: 14),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: navy,
        side: const BorderSide(color: border),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      ),
    ),
    dataTableTheme: const DataTableThemeData(
      headingRowColor: WidgetStatePropertyAll(Color(0xFFF7F9FB)),
      dividerThickness: 1,
      dataRowMinHeight: 54,
      dataRowMaxHeight: 72,
    ),
  );
}

