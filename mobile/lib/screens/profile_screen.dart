import 'package:flutter/material.dart';

import '../config.dart';
import '../theme.dart';
import '../widgets/common.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  Future<void> _signOut(BuildContext context) async {
    final state = AppScope.read(context);
    if (state.pendingUpdates > 0) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: const Text('Sign out?'),
          content: Text('${state.pendingUpdates} updates are not sent yet and will be lost.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(dialog, false), child: const Text('Stay')),
            TextButton(onPressed: () => Navigator.pop(dialog, true), child: const Text('Sign out')),
          ],
        ),
      );
      if (ok != true) return;
    }
    await state.signOut();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final p = state.profile;
    final text = Theme.of(context).textTheme;
    final rows = <(String, String)>[
      ('ID', p?.partnerId ?? ''),
      ('Vehicle', p == null ? '' : '${capitalise(p.vehicleType)} · ${p.regNo}'),
      ('Shift', p?.shift ?? ''),
      ('Rating', p == null ? '' : p.rating.toStringAsFixed(1)),
      ('Status', p == null ? '' : capitalise(p.status.replaceAll('_', ' '))),
      ('Push', state.push.available ? 'On' : 'Off (Demo mode)'),
      ('Server', apiUrl),
    ];
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text(p?.name ?? '', style: text.headlineSmall),
      const SizedBox(height: 12),
      GlassCard(
        child: Column(children: [
          for (final (label, value) in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(children: [
                SizedBox(width: 90, child: Text(label, style: text.bodySmall)),
                Expanded(child: Text(value)),
              ]),
            ),
        ]),
      ),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        onPressed: () => _signOut(context),
        icon: const Icon(Icons.logout, color: Palette.critical),
        label: const Text('Sign out'),
      ),
    ]);
  }
}
