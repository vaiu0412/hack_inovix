import 'package:deport_partner/api/endpoints.dart';
import 'package:deport_partner/api/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final row = {
    'delivery_id': 'D06',
    'customer': 'KMCH Hospital (Insulin)',
    'address_area': 'KMCH - Avinashi Road',
    'customer_phone': '+91 90000 10006',
    'priority': 'medical',
    'status': 'in_transit',
    'planned_eta': '10:50',
    'deadline': '11:30',
    'stop_order': 6,
    'lat': 11.0312,
    'lng': 77.0375,
    'pod_at': null,
  };

  test('a delivery from the API and its next step', () {
    final d = Delivery.fromJson(row);
    expect(d.id, 'D06');
    expect(d.medical, isTrue);
    expect(d.proofDone, isFalse);
    expect(d.nextStep, ('delivered', 'Delivered'));
    expect(d.stage, 'On the way');
    expect(d.withStatus('delivered').done, isTrue);
    expect(Delivery.fromJson({...row, 'status': 'assigned'}).nextStep, ('accepted', 'Accept'));
    expect(Delivery.fromJson({...row, 'status': 'delivered'}).nextStep, isNull);
  });

  test('endpoints resolve to method and path', () {
    expect(Endpoints.resolve(Endpoints.step, {'id': 'D07', 'step': 'picked_up'}),
        ('POST', '/me/deliveries/D07/picked_up'));
    expect(Endpoints.resolve(Endpoints.me), ('GET', '/me'));
  });

  test('a customer order', () {
    final o = CustomerOrder.fromJson({
      'delivery_id': 'D07', 'area': 'Ukkadam', 'status': 'in_transit', 'stage': 'On the way', 'eta': '09:15',
      'deadline': '11:00', 'partner_first_name': 'Karthik', 'vehicle': 'bike', 'proof': false,
      'track_url': 'https://example.com/track?code=abc',
    });
    expect(o.step, 3);
    expect(o.done, isFalse);
    expect(CustomerOrder.fromJson({'status': 'delivered', 'proof': true}).done, isTrue);
  });

  test('profile and live change', () {
    final p = Profile.fromJson({'partner_id': 'DP102', 'name': 'Karthik R', 'status': 'on_duty', 'rating': 4.5});
    expect(p.onDuty, isTrue);
    expect(p.firstName, 'Karthik');
    final change = LiveChange.fromJson({'id': 12, 'kind': 'offer', 'data': {'delivery_id': 'D31', 'result': 'Sent'}});
    expect(change.kind, 'offer');
    expect(change.data['delivery_id'], 'D31');
  });
}
