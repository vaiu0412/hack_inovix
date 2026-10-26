import 'package:flutter/material.dart';

import '../theme.dart';
import '../widgets/common.dart';

/// Notifications: messages from the branch (route changes, new orders) and what happened to my reports.
class InboxScreen extends StatefulWidget {
  const InboxScreen({super.key});

  @override
  State<InboxScreen> createState() => _InboxScreenState();
}

class _InboxScreenState extends State<InboxScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => AppScope.read(context).markMessagesRead());
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final text = Theme.of(context).textTheme;
    return RefreshIndicator(
      onRefresh: state.refresh,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        Text('Messages', style: text.titleMedium),
        const SizedBox(height: 8),
        if (state.messages.isEmpty) const EmptyState(Icons.mark_email_read_outlined, 'No messages.'),
        for (final m in state.messages)
          GlassCard(
            accent: m.read ? null : Palette.primary,
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(m.read ? Icons.drafts_outlined : Icons.mark_email_unread, color: Palette.muted, size: 20),
              const SizedBox(width: 10),
              Expanded(child: Text(m.text)),
              Text(m.time.length >= 5 ? m.time.substring(0, 5) : m.time, style: text.bodySmall),
            ]),
          ),
        const SizedBox(height: 12),
        Text('My reports', style: text.titleMedium),
        const SizedBox(height: 8),
        if (state.incidents.isEmpty) const EmptyState(Icons.campaign_outlined, 'Nothing reported yet.'),
        for (final i in state.incidents)
          GlassCard(
            child: Row(children: [
              Expanded(child: Text(i.headline)),
              StatusPill(capitalise(i.status),
                  color: i.status == 'accepted' ? Palette.normal : i.status == 'rejected' ? Palette.muted : Palette.delayed),
            ]),
          ),
      ]),
    );
  }
}
