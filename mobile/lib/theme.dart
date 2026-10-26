import 'package:flutter/material.dart';

/// The DEPORT dark glass look (same tokens as assets/style.css).
class Palette {
  static const background = Color(0xFF070B14);
  static const navy = Color(0xFF0B1E3F);
  static const primary = Color(0xFF3B82F6);
  static const text = Color(0xFFF8FAFC);
  static const body = Color(0xFFCBD5E1);
  static const muted = Color(0xFF94A3B8);
  static const glass = Color(0x0FFFFFFF); // rgba(255,255,255,.06)
  static const border = Color(0x1FFFFFFF); // rgba(255,255,255,.12)
  static const normal = Color(0xFF22C55E);
  static const delayed = Color(0xFFFACC15);
  static const critical = Color(0xFFF43F5E);
  static const available = Color(0xFF38BDF8);
}

ThemeData deportTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: Palette.primary,
    brightness: Brightness.dark,
    surface: Palette.background,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: Palette.background,
    appBarTheme: const AppBarTheme(backgroundColor: Palette.background, foregroundColor: Palette.text, elevation: 0),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(52),
        foregroundColor: Palette.text,
        side: const BorderSide(color: Palette.border),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Palette.glass,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: const BorderSide(color: Palette.border)),
    ),
    navigationBarTheme: const NavigationBarThemeData(backgroundColor: Palette.navy, indicatorColor: Color(0x333B82F6)),
    textTheme: const TextTheme(
      headlineSmall: TextStyle(color: Palette.text, fontWeight: FontWeight.w700),
      titleMedium: TextStyle(color: Palette.text, fontWeight: FontWeight.w600),
      bodyMedium: TextStyle(color: Palette.body),
      bodySmall: TextStyle(color: Palette.muted),
    ),
  );
}
