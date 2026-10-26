import 'dart:async';

import 'package:flutter/material.dart';

import '../widgets/common.dart';
import 'deliveries_screen.dart';
import 'inbox_screen.dart';
import 'offer_screen.dart';
import 'profile_screen.dart';
import 'report_screen.dart';
import 'today_screen.dart';

/// Signed in: five tabs. A new offer opens full-screen by itself (once per order); notices show as snackbars.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  static const _titles = ['Today', 'Orders', 'Report', 'Inbox', 'Profile'];
  int _tab = 0;
  final Set<String> _presented = {};
  StreamSubscription<String>? _notices;
  bool _offerOpen = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _notices = AppScope.read(context).notices.listen((text) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
      });
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _notices?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    if (lifecycle == AppLifecycleState.resumed) {
      final state = AppScope.read(context);
      state.queue.flush();
      state.refresh();
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final offers = AppScope.of(context).offers;
    final fresh = offers.where((o) => !_presented.contains(o.id)).toList();
    if (fresh.isNotEmpty && !_offerOpen) {
      _presented.add(fresh.first.id);
      _offerOpen = true;
      WidgetsBinding.instance.addPostFrameCallback((_) async {
        await Navigator.of(context).push(MaterialPageRoute<void>(
            fullscreenDialog: true, builder: (_) => OfferScreen(offer: fresh.first)));
        _offerOpen = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    const pages = [TodayScreen(), DeliveriesScreen(), ReportScreen(), InboxScreen(), ProfileScreen()];
    return Scaffold(
      appBar: AppBar(title: Text(_titles[_tab])),
      body: SafeArea(child: IndexedStack(index: _tab, children: pages)),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: [
          const NavigationDestination(icon: Icon(Icons.today), label: 'Today'),
          NavigationDestination(
            icon: Badge(isLabelVisible: state.offers.isNotEmpty, label: Text('${state.offers.length}'),
                child: const Icon(Icons.inventory_2)),
            label: 'Orders',
          ),
          const NavigationDestination(icon: Icon(Icons.campaign), label: 'Report'),
          NavigationDestination(
            icon: Badge(isLabelVisible: state.unread > 0, label: Text('${state.unread}'),
                child: const Icon(Icons.notifications)),
            label: 'Inbox',
          ),
          const NavigationDestination(icon: Icon(Icons.person), label: 'Profile'),
        ],
      ),
    );
  }
}
