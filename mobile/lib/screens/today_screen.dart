import 'package:flutter/material.dart';

import '../theme.dart';
import '../widgets/common.dart';
import 'deliveries_screen.dart';
import 'offer_screen.dart';

/// Today: greeting, how far along the day is, the next stop with its one button, and any waiting offers.
class TodayScreen extends StatelessWidget {
  const TodayScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final p = state.profile;
    final text = Theme.of(context).textTheme;
    final done = state.deliveries.length - state.open.length;
    return RefreshIndicator(
      onRefresh: state.refresh,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        Text('Hi ${p?.firstName ?? ''}', style: text.headlineSmall),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 6, children: [
          StatusPill(state.liveConnected ? 'Live' : 'Offline',
              color: state.liveConnected ? Palette.normal : Palette.muted),
          if (state.pendingUpdates > 0) StatusPill('${state.pendingUpdates} waiting to send', color: Palette.delayed),
          StatusPill(state.location.status, color: state.location.running ? Palette.available : Palette.muted),
        ]),
        const SizedBox(height: 16),
        GlassCard(
          child: Row(children: [
            SizedBox(
              width: 56,
              height: 56,
              child: CircularProgressIndicator(
                value: state.deliveries.isEmpty ? 0 : done / state.deliveries.length,
                strokeWidth: 6,
                backgroundColor: Palette.border,
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('$done of ${state.deliveries.length} delivered', style: text.titleMedium),
                Text(p == null ? '' : '${capitalise(p.vehicleType)} ${p.regNo} · ${p.shift}', style: text.bodySmall),
              ]),
            ),
          ]),
        ),
        for (final o in state.offers)
          GlassCard(
            accent: Palette.delayed,
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.notifications_active, color: Palette.delayed),
              title: Text('New order ${o.id}'),
              subtitle: Text('${o.area} · by ${o.deadline}'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  fullscreenDialog: true, builder: (_) => OfferScreen(offer: o))),
            ),
          ),
        const SizedBox(height: 4),
        Text('Next stop', style: text.titleMedium),
        const SizedBox(height: 8),
        if (state.nextStop == null)
          const EmptyState(Icons.check_circle_outline, 'All done for now.')
        else
          DeliveryCard(delivery: state.nextStop!),
      ]),
    );
  }
}
