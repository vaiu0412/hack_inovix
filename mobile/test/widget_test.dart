import 'package:deport_partner/screens/login_screen.dart';
import 'package:deport_partner/state/app_state.dart';
import 'package:deport_partner/theme.dart';
import 'package:deport_partner/widgets/common.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('sign-in asks for ID and password before calling the server', (tester) async {
    await tester.pumpWidget(AppScope(
      state: AppState(),
      child: MaterialApp(theme: deportTheme(), home: const LoginScreen()),
    ));
    expect(find.text('Sign in'), findsOneWidget);
    expect(find.textContaining('Partner@'), findsNothing); // never shows demo passwords
    await tester.tap(find.text('Sign in'));
    await tester.pump();
    expect(find.text('Enter your ID and password.'), findsOneWidget);
  });
}
