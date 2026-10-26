import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../theme.dart';

/// Gives every screen the one AppState (rebuilds listeners when it changes).
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  /// For event handlers and lifecycle callbacks: the state without rebuilding on its changes.
  static AppState read(BuildContext context) => context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;
}

/// The design system's glass card: translucent fill, thin border, radius 18.
class GlassCard extends StatelessWidget {
  const GlassCard({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.accent});

  final Widget child;
  final EdgeInsets padding;
  final Color? accent;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: padding,
        decoration: BoxDecoration(
          color: Palette.glass,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: accent ?? Palette.border, width: accent == null ? 1 : 1.5),
        ),
        child: child,
      );
}

/// A small coloured label ("On the way", "Medical").
class StatusPill extends StatelessWidget {
  const StatusPill(this.text, {super.key, this.color = Palette.available});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: color.withValues(alpha: 0.16), borderRadius: BorderRadius.circular(99)),
        child: Text(text, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
      );
}

Color stageColor(Delivery d) => switch (d.status) {
      'delivered' => Palette.normal,
      'failed' => Palette.critical,
      'delayed' => Palette.delayed,
      'assigned' => Palette.delayed,
      _ => d.risk == 'Critical' ? Palette.critical : Palette.available,
    };

Color priorityColor(String priority) => switch (priority) {
      'medical' => Palette.critical,
      'perishable' || 'express' => Palette.delayed,
      _ => Palette.muted,
    };

String capitalise(String text) => text.isEmpty ? text : text[0].toUpperCase() + text.substring(1);

/// One-line empty state (icon + text).
class EmptyState extends StatelessWidget {
  const EmptyState(this.icon, this.text, {super.key});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 40),
        child: Column(children: [
          Icon(icon, size: 40, color: Palette.muted),
          const SizedBox(height: 8),
          Text(text, style: Theme.of(context).textTheme.bodySmall, textAlign: TextAlign.center),
        ]),
      );
}
