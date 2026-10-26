import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/models.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Customers: my orders – the ones on their way first (stage, ETA, partner's first name, a link to the live map),
/// then the delivered ones. Refreshes every 30 s and on pull-down.
class CustomerScreen extends StatelessWidget {
  const CustomerScreen({super.key});

  static const _steps = ['Order received', 'Partner assigned', 'Picked up', 'On the way', 'Delivered'];

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final text = Theme.of(context).textTheme;
    final active = state.myOrders.where((o) => !o.done).toList();
    final done = state.myOrders.where((o) => o.done).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('My orders'), actions: [
        IconButton(tooltip: 'Sign out', icon: const Icon(Icons.logout), onPressed: () => AppScope.read(context).signOut()),
      ]),
      body: RefreshIndicator(
        onRefresh: state.refreshOrders,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          if (state.myOrders.isEmpty) const EmptyState(Icons.inventory_2_outlined, 'No orders yet for this number or email.'),
          for (final o in active) _OrderCard(order: o, steps: _steps),
          if (done.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Delivered', style: text.titleMedium),
            const SizedBox(height: 8),
            for (final o in done)
              GlassCard(
                child: Row(children: [
                  Expanded(child: Text('${o.id} · ${o.area}')),
                  Text(o.deliveredAt.length >= 16 ? o.deliveredAt.substring(0, 16) : o.stage, style: text.bodySmall),
                  if (o.proof) const Padding(padding: EdgeInsets.only(left: 6), child: Icon(Icons.verified, size: 18, color: Palette.normal)),
                ]),
              ),
          ],
        ]),
      ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  const _OrderCard({required this.order, required this.steps});

  final CustomerOrder order;
  final List<String> steps;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final o = order;
    return GlassCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('DELIVERY ${o.id}', style: text.bodySmall),
        const SizedBox(height: 2),
        Text(o.stage, style: text.headlineSmall),
        const SizedBox(height: 4),
        Text(o.eta.isEmpty ? 'We are planning your delivery · promised by ${o.deadline}'
            : 'Expected by ${o.eta} · promised by ${o.deadline}'),
        const SizedBox(height: 12),
        Row(children: [
          for (var i = 0; i < steps.length; i++)
            Expanded(
              child: Container(
                height: 6,
                margin: const EdgeInsets.symmetric(horizontal: 2),
                decoration: BoxDecoration(
                  color: i <= o.step ? Palette.primary : Palette.border,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            ),
        ]),
        if (o.partnerFirstName.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('Your partner: ${o.partnerFirstName}${o.vehicle.isEmpty ? '' : ' · ${capitalise(o.vehicle)}'}',
              style: text.bodyMedium),
        ],
        if (o.trackUrl.isNotEmpty) ...[
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => launchUrl(Uri.parse(o.trackUrl), mode: LaunchMode.externalApplication),
            icon: const Icon(Icons.map),
            label: const Text('Live map'),
          ),
        ],
      ]),
    );
  }
}
