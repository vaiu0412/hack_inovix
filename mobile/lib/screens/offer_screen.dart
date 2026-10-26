import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/models.dart';
import '../config.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Full-screen card for a new order: Accept, or Can't take with a reason. Opens by itself when an offer arrives
/// (live feed or push). Answering works offline too (sent when the network is back).
class OfferScreen extends StatefulWidget {
  const OfferScreen({super.key, required this.offer});

  final Delivery offer;

  @override
  State<OfferScreen> createState() => _OfferScreenState();
}

class _OfferScreenState extends State<OfferScreen> {
  bool _declining = false;
  String? _reason;

  @override
  void initState() {
    super.initState();
    HapticFeedback.heavyImpact();
  }

  Future<void> _answer(bool accept) async {
    final state = AppScope.read(context);
    final navigator = Navigator.of(context);
    if (accept) {
      await state.accept(widget.offer);
    } else {
      await state.decline(widget.offer, _reason!);
    }
    if (navigator.canPop()) navigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final o = widget.offer;
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('New order'), automaticallyImplyLeading: false),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            GlassCard(
              accent: priorityColor(o.priority),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  StatusPill(capitalise(o.priority), color: priorityColor(o.priority)),
                  const Spacer(),
                  Text(o.id, style: text.bodySmall),
                ]),
                const SizedBox(height: 12),
                Text(o.customer, style: text.headlineSmall),
                const SizedBox(height: 4),
                Text(o.area, style: text.bodyMedium),
                const SizedBox(height: 16),
                Row(children: [
                  _Fact('Deliver by', o.deadline),
                  _Fact('ETA', o.eta.isEmpty ? '—' : o.eta),
                ]),
                if (o.callNote.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(o.callNote, style: const TextStyle(color: Palette.delayed)),
                ],
              ]),
            ),
            const Spacer(),
            if (!_declining) ...[
              FilledButton.icon(
                onPressed: () => _answer(true),
                icon: const Icon(Icons.check_circle),
                label: const Text('Accept'),
              ),
              const SizedBox(height: 10),
              OutlinedButton(onPressed: () => setState(() => _declining = true), child: const Text("Can't take")),
            ] else ...[
              Text('Why?', style: text.titleMedium),
              const SizedBox(height: 8),
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final r in declineReasons)
                  ChoiceChip(label: Text(r), selected: _reason == r, onSelected: (_) => setState(() => _reason = r)),
              ]),
              const SizedBox(height: 16),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Palette.critical),
                onPressed: _reason == null ? null : () => _answer(false),
                child: const Text('Send'),
              ),
              TextButton(onPressed: () => setState(() => _declining = false), child: const Text('Back')),
            ],
          ]),
        ),
      ),
    );
  }
}

class _Fact extends StatelessWidget {
  const _Fact(this.label, this.value);

  final String label, value;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          Text(value, style: Theme.of(context).textTheme.titleMedium),
        ]),
      );
}
