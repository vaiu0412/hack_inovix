import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/models.dart';
import '../theme.dart';
import '../widgets/common.dart';
import 'proof_sheet.dart';

/// All of today's orders, in route order, each with its one next step.
class DeliveriesScreen extends StatelessWidget {
  const DeliveriesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final items = state.deliveries;
    return RefreshIndicator(
      onRefresh: state.refresh,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        Text('${state.open.length} left · ${items.length - state.open.length} done',
            style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 12),
        if (items.isEmpty) const EmptyState(Icons.inventory_2_outlined, 'No orders yet.'),
        for (final d in items) DeliveryCard(delivery: d),
      ]),
    );
  }
}

class DeliveryCard extends StatelessWidget {
  const DeliveryCard({super.key, required this.delivery});

  final Delivery delivery;

  Future<void> _next(BuildContext context) async {
    final step = delivery.nextStep;
    if (step == null) return;
    if (step.$1 == 'delivered' && delivery.medical && !delivery.proofDone) {
      await showProofSheet(context, delivery); // medical: photo + customer code first
    } else {
      await AppScope.read(context).advance(delivery);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = delivery;
    final text = Theme.of(context).textTheme;
    final step = d.nextStep;
    return GlassCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${d.stopOrder}. ${d.customer}', style: text.titleMedium)),
          StatusPill(d.stage, color: stageColor(d)),
        ]),
        const SizedBox(height: 4),
        Text('${d.id} · ${d.area} · ${capitalise(d.priority)}', style: text.bodySmall),
        const SizedBox(height: 4),
        Text('ETA ${d.eta.isEmpty ? '—' : d.eta} · due ${d.deadline}', style: text.bodyMedium),
        if (d.risk == 'Critical' || d.risk == 'High')
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text('${d.risk} risk – an alert affects this stop', style: const TextStyle(color: Palette.delayed)),
          ),
        if (!d.done) ...[
          const SizedBox(height: 12),
          Row(children: [
            if (step != null)
              Expanded(child: FilledButton(onPressed: () => _next(context), child: Text(step.$2))),
            const SizedBox(width: 8),
            IconButton.outlined(
              tooltip: 'Call customer',
              onPressed: () => launchUrl(Uri.parse('tel:${d.phone.replaceAll(' ', '')}')),
              icon: const Icon(Icons.call),
            ),
            if (d.lat != null && d.lng != null)
              IconButton.outlined(
                tooltip: 'Directions',
                onPressed: () => launchUrl(
                    Uri.parse('https://www.google.com/maps/dir/?api=1&destination=${d.lat},${d.lng}'),
                    mode: LaunchMode.externalApplication),
                icon: const Icon(Icons.directions),
              ),
          ]),
        ],
      ]),
    );
  }
}
