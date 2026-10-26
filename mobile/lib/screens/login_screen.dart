import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Sign in: partners with ID + password, or anyone (partners and customers) with a 6-digit code sent by SMS or
/// email. Customers type the mobile number or email on their order.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _id = TextEditingController();
  final _password = TextEditingController();
  final _code = TextEditingController();
  bool _withCode = false, _codeSent = false, _busy = false, _hidden = true;
  String? _error, _info, _demoCode;

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on ApiException catch (e) {
      setState(() => _error = e.offline ? 'No connection. Try again.' : e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    final state = AppScope.read(context);
    if (_id.text.trim().isEmpty || (!_withCode && _password.text.isEmpty)) {
      setState(() => _error = _withCode ? 'Enter your mobile number or email.' : 'Enter your ID and password.');
      return;
    }
    if (!_withCode) return _run(() => state.signIn(_id.text, _password.text));
    if (!_codeSent) {
      return _run(() async {
        final (message, demo) = await state.requestCode(_id.text);
        setState(() {
          _codeSent = true;
          _info = message;
          _demoCode = demo;
        });
      });
    }
    return _run(() => state.signInWithCode(_id.text, _code.text));
  }

  void _switch(bool withCode) => setState(() {
        _withCode = withCode;
        _codeSent = false;
        _error = _info = _demoCode = null;
      });

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Icon(Icons.local_shipping_rounded, size: 48, color: Palette.primary),
                const SizedBox(height: 12),
                Text('DEPORT', textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 4),
                Text('Partners and customers', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
                const SizedBox(height: 20),
                SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(value: false, label: Text('Password')),
                    ButtonSegment(value: true, label: Text('Code (SMS / email)')),
                  ],
                  selected: {_withCode},
                  onSelectionChanged: (picked) => _switch(picked.first),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _id,
                  enabled: !_codeSent,
                  keyboardType: _withCode ? TextInputType.emailAddress : TextInputType.text,
                  autofillHints: const [AutofillHints.username],
                  decoration: InputDecoration(
                    labelText: _withCode ? 'Mobile number or email' : 'Email or ID',
                    hintText: _withCode ? '98765 43210' : 'DP102',
                  ),
                  textInputAction: TextInputAction.next,
                ),
                const SizedBox(height: 12),
                if (!_withCode)
                  TextField(
                    controller: _password,
                    obscureText: _hidden,
                    autofillHints: const [AutofillHints.password],
                    onSubmitted: (_) => _submit(),
                    decoration: InputDecoration(
                      labelText: 'Password',
                      suffixIcon: IconButton(
                        icon: Icon(_hidden ? Icons.visibility : Icons.visibility_off),
                        onPressed: () => setState(() => _hidden = !_hidden),
                      ),
                    ),
                  )
                else if (_codeSent) ...[
                  if (_info != null) Text(_info!, style: const TextStyle(color: Palette.normal)),
                  if (_demoCode != null)
                    Text('DEMO code: $_demoCode (no email / SMS set up)', style: const TextStyle(color: Palette.delayed)),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _code,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    autofillHints: const [AutofillHints.oneTimeCode],
                    onSubmitted: (_) => _submit(),
                    decoration: const InputDecoration(labelText: '6-digit code', counterText: ''),
                  ),
                  TextButton(onPressed: _busy ? null : () => _switch(true), child: const Text('Use another number')),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: Palette.critical)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: _busy
                      ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(!_withCode ? 'Sign in' : _codeSent ? 'Sign in' : 'Send code'),
                ),
              ]),
            ),
          ),
        ),
      );
}
