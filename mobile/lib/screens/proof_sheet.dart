import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Proof of delivery for medical orders: a photo + the customer's 4-digit code. (The server also accepts a
/// signature; the web app has the signature pad.) Needs a connection – the photo is uploaded at once.
Future<void> showProofSheet(BuildContext context, Delivery delivery) => showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Palette.navy,
      builder: (sheet) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(sheet).viewInsets.bottom),
        child: _ProofSheet(delivery: delivery),
      ),
    );

class _ProofSheet extends StatefulWidget {
  const _ProofSheet({required this.delivery});

  final Delivery delivery;

  @override
  State<_ProofSheet> createState() => _ProofSheetState();
}

class _ProofSheetState extends State<_ProofSheet> {
  final _code = TextEditingController();
  Uint8List? _photo;
  bool _codeSent = false, _busy = false;
  String? _demoCode, _error;

  Future<void> _takePhoto() async {
    final shot = await ImagePicker().pickImage(source: ImageSource.camera, maxWidth: 1600, imageQuality: 80);
    if (shot != null) {
      final bytes = await shot.readAsBytes();
      setState(() => _photo = bytes);
    }
  }

  Future<void> _sendCode() => _run(() async {
        _demoCode = await AppScope.read(context).sendProofCode(widget.delivery);
        _codeSent = true;
      });

  Future<void> _deliver() => _run(() async {
        final navigator = Navigator.of(context);
        await AppScope.read(context).deliverWithProof(widget.delivery, photo: _photo!, code: _code.text.trim());
        navigator.pop();
      });

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on ApiException catch (e) {
      _error = e.offline ? 'No connection – proof needs the network.' : e.message;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ready = _photo != null && _code.text.trim().length == 4 && !_busy;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('Proof of delivery', style: Theme.of(context).textTheme.titleMedium),
          Text('${widget.delivery.id} · ${widget.delivery.customer}', style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 16),
          if (_photo != null)
            ClipRRect(borderRadius: BorderRadius.circular(14), child: Image.memory(_photo!, height: 160, fit: BoxFit.cover)),
          OutlinedButton.icon(
            onPressed: _busy ? null : _takePhoto,
            icon: const Icon(Icons.photo_camera),
            label: Text(_photo == null ? 'Take photo' : 'Retake photo'),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: _busy ? null : _sendCode,
            icon: const Icon(Icons.sms),
            label: Text(_codeSent ? 'Send code again' : 'Send code to customer'),
          ),
          if (_demoCode != null) ...[
            const SizedBox(height: 8),
            Text('DEMO code: $_demoCode (no messaging set up)', style: const TextStyle(color: Palette.delayed)),
          ],
          const SizedBox(height: 10),
          TextField(
            controller: _code,
            keyboardType: TextInputType.number,
            maxLength: 4,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: "Customer's 4-digit code", counterText: ''),
          ),
          if (_error != null) Text(_error!, style: const TextStyle(color: Palette.critical)),
          const SizedBox(height: 12),
          FilledButton.icon(onPressed: ready ? _deliver : null, icon: const Icon(Icons.verified), label: const Text('Delivered')),
        ]),
      ),
    );
  }
}
