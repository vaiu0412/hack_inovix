import 'package:flutter/material.dart';

import 'screens/customer_screen.dart';
import 'screens/home_shell.dart';
import 'screens/login_screen.dart';
import 'services/push_service.dart';
import 'state/app_state.dart';
import 'theme.dart';
import 'widgets/common.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await PushService.initialise(); // false without google-services.json: no push, everything else works
  final state = AppState();
  runApp(AppScope(state: state, child: const DeportApp()));
  await state.boot();
}

class DeportApp extends StatelessWidget {
  const DeportApp({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return MaterialApp(
      title: 'DEPORT',
      debugShowCheckedModeBanner: false,
      theme: deportTheme(),
      home: state.booting
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : !state.signedIn
              ? const LoginScreen()
              : state.isCustomer
                  ? const CustomerScreen()
                  : const HomeShell(),
    );
  }
}
