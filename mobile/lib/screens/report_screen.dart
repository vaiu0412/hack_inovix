import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../theme.dart';
import '../widgets/common.dart';

/// Report a problem on the route: tap a type, and/or say it (voice note), and/or take a photo, and/or type it.
/// The branch gets an alert with a plan. Needs a connection.
class ReportScreen extends StatefulWidget {
  const ReportScreen({super.key});

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  final _text = TextEditingController();
  final _recorder = AudioRecorder();
  String? _type;
  Uint8List? _photo, _voice;
  bool _recording = false, _busy = false;
  String? _result, _error;

  @override
  void dispose() {
    _recorder.dispose();
    _text.dispose();
    super.dispose();
  }

  Future<void> _takePhoto() async {
    final shot = await ImagePicker().pickImage(source: ImageSource.camera, maxWidth: 1600, imageQuality: 80);
    if (shot != null) {
      final bytes = await shot.readAsBytes();
      setState(() => _photo = bytes);
    }
  }

  Future<void> _toggleVoice() async {
    if (_recording) {
      final path = await _recorder.stop();
      final bytes = path == null ? null : await File(path).readAsBytes();
      setState(() {
        _recording = false;
        _voice = bytes;
      });
      return;
    }
    if (!await _recorder.hasPermission()) {
      setState(() => _error = 'Allow the microphone to record.');
      return;
    }
    final dir = await getTemporaryDirectory();
    await _recorder.start(const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
        path: '${dir.path}/deport-note.wav'); // WAV: what the server's speech recognition reads
    setState(() {
      _recording = true;
      _voice = null;
    });
  }

  Future<void> _send() async {
    if (_type == null && _text.text.trim().isEmpty && _photo == null && _voice == null) {
      setState(() => _error = 'Pick a type, or say / type / photograph what happened.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final incident = await AppScope.read(context)
          .report(text: _text.text.trim(), quickType: _type, photo: _photo, voice: _photo == null ? _voice : null);
      setState(() {
        _result = 'Sent: ${incident.headline}';
        _type = null;
        _photo = null;
        _voice = null;
        _text.clear();
      });
    } on ApiException catch (e) {
      setState(() => _error = e.offline ? 'No connection – try again or call your branch.' : e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('What happened?', style: text.titleMedium),
      const SizedBox(height: 10),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final entry in issueTypes.entries)
          ChoiceChip(
            label: Text(entry.value),
            selected: _type == entry.key,
            onSelected: (on) => setState(() => _type = on ? entry.key : null),
          ),
      ]),
      const SizedBox(height: 14),
      TextField(
        controller: _text,
        minLines: 2,
        maxLines: 4,
        decoration: const InputDecoration(hintText: 'Avinashi Rd accident, full block, 2 hours'),
      ),
      const SizedBox(height: 12),
      Row(children: [
        Expanded(
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _toggleVoice,
            icon: Icon(_recording ? Icons.stop_circle : Icons.mic, color: _recording ? Palette.critical : null),
            label: Text(_recording ? 'Stop' : (_voice == null ? 'Voice' : 'Voice ✓')),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: OutlinedButton.icon(
            onPressed: _busy ? null : _takePhoto,
            icon: const Icon(Icons.photo_camera),
            label: Text(_photo == null ? 'Photo' : 'Photo ✓'),
          ),
        ),
      ]),
      if (_photo != null && _voice != null)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text('The photo is sent; type what you said.', style: text.bodySmall),
        ),
      if (_error != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(_error!, style: const TextStyle(color: Palette.critical))),
      if (_result != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(_result!, style: const TextStyle(color: Palette.normal))),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: _busy || _recording ? null : _send,
        icon: const Icon(Icons.campaign),
        label: Text(_busy ? 'Sending…' : 'Send to branch'),
      ),
    ]);
  }
}
