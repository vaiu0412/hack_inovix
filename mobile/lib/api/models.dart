/// Plain data classes for what the API returns (only the fields the app shows or needs).
library;

String _s(Object? v, [String fallback = '']) => v == null ? fallback : v.toString();
int _i(Object? v) => v is num ? v.toInt() : int.tryParse(_s(v)) ?? 0;
double? _d(Object? v) => v is num ? v.toDouble() : double.tryParse(_s(v));

class User {
  User({required this.userId, required this.name, required this.role, this.dpId, this.branchId, this.branchName});

  factory User.fromJson(Map<String, dynamic> j) => User(
        userId: _s(j['user_id']),
        name: _s(j['display_name'], _s(j['user_id'])),
        role: _s(j['role']),
        dpId: j['dp_id'] as String?,
        branchId: j['branch_id'] as String?,
        branchName: j['branch_name'] as String?,
      );

  final String userId, name, role;
  final String? dpId, branchId, branchName;
  bool get isPartner => role == 'partner' && dpId != null;
  bool get isCustomer => role == 'customer';
}

class Profile {
  Profile.fromJson(Map<String, dynamic> j)
      : partnerId = _s(j['partner_id']),
        name = _s(j['name']),
        status = _s(j['status']),
        vehicleType = _s(j['vehicle_type']),
        regNo = _s(j['reg_no']),
        shift = _s(j['shift']),
        rating = _d(j['rating']) ?? 0,
        assigned = _i(j['assigned']),
        delivered = _i(j['delivered']),
        pending = _i(j['pending']),
        nextStop = _s(j['next_stop']),
        nextEta = _s(j['next_eta']);

  final String partnerId, name, status, vehicleType, regNo, shift, nextStop, nextEta;
  final double rating;
  final int assigned, delivered, pending;
  bool get onDuty => status == 'on_duty';
  String get firstName => name.split(' ').first;
}

/// One order. `status` follows the server: assigned -> accepted -> picked_up -> in_transit -> delivered.
class Delivery {
  Delivery.fromJson(Map<String, dynamic> j)
      : id = _s(j['delivery_id']),
        customer = _s(j['customer']),
        area = _s(j['address_area']),
        phone = _s(j['customer_phone']),
        priority = _s(j['priority'], 'standard'),
        status = _s(j['status']),
        eta = _s(j['planned_eta']),
        deadline = _s(j['deadline']),
        stopOrder = _i(j['stop_order']),
        lat = _d(j['lat']),
        lng = _d(j['lng']),
        risk = _s(j['risk']),
        offerStatus = _s(j['offer_status']),
        callNote = _s(j['call_note']),
        proofDone = j['pod_at'] != null;

  Delivery._copy(Delivery d, {required this.status})
      : id = d.id,
        customer = d.customer,
        area = d.area,
        phone = d.phone,
        priority = d.priority,
        eta = d.eta,
        deadline = d.deadline,
        stopOrder = d.stopOrder,
        lat = d.lat,
        lng = d.lng,
        risk = d.risk,
        offerStatus = d.offerStatus,
        callNote = d.callNote,
        proofDone = d.proofDone;

  final String id, customer, area, phone, priority, status, eta, deadline, risk, offerStatus, callNote;
  final int stopOrder;
  final double? lat, lng;
  final bool proofDone;

  Delivery withStatus(String newStatus) => Delivery._copy(this, status: newStatus);
  bool get done => status == 'delivered' || status == 'failed';
  bool get medical => priority == 'medical';

  /// The next step and its button label, or null when there is none.
  (String, String)? get nextStep => switch (status) {
        'assigned' => ('accepted', 'Accept'),
        'accepted' => ('picked_up', 'Picked up'),
        'picked_up' => ('in_transit', 'Start'),
        'in_transit' || 'pending' || 'delayed' || 'rescheduled' => ('delivered', 'Delivered'),
        _ => null,
      };

  String get stage => switch (status) {
        'assigned' => 'New',
        'accepted' => 'Accepted',
        'picked_up' => 'Picked up',
        'in_transit' || 'pending' => 'On the way',
        'delayed' => 'Delayed',
        'delivered' => 'Delivered',
        'failed' => 'Not delivered',
        _ => status,
      };
}

class Message {
  Message.fromJson(Map<String, dynamic> j)
      : id = _i(j['id']),
        time = _s(j['created_at']),
        text = _s(j['text']),
        read = _i(j['read']) == 1;

  final int id;
  final String time, text;
  final bool read;
}

class Incident {
  Incident.fromJson(Map<String, dynamic> j)
      : id = _i(j['issue_id']),
        headline = _s(j['headline'], _s(j['summary'])),
        status = _s(j['status']),
        time = _s(j['created_at']);

  final int id;
  final String headline, status, time;
}

/// One row of the live feed (/ws/partner): kind is offer | message | event.
class LiveChange {
  LiveChange.fromJson(Map<String, dynamic> j)
      : id = _i(j['id']),
        kind = _s(j['kind']),
        data = (j['data'] as Map?)?.cast<String, dynamic>() ?? const {};

  final int id;
  final String kind;
  final Map<String, dynamic> data;
}

/// A customer's order (/my/orders): only what the customer may see – no phone numbers, no other stops.
class CustomerOrder {
  CustomerOrder.fromJson(Map<String, dynamic> j)
      : id = _s(j['delivery_id']),
        area = _s(j['area']),
        status = _s(j['status']),
        stage = _s(j['stage']),
        eta = _s(j['eta']),
        deadline = _s(j['deadline']),
        partnerFirstName = _s(j['partner_first_name']),
        vehicle = _s(j['vehicle']),
        deliveredAt = _s(j['delivered_at']),
        proof = j['proof'] == true,
        branch = _s(j['branch']),
        trackUrl = _s(j['track_url']);

  final String id, area, status, stage, eta, deadline, partnerFirstName, vehicle, deliveredAt, branch, trackUrl;
  final bool proof;
  bool get done => status == 'delivered' || status == 'failed';

  /// 0..4 along Order received → Partner assigned → Picked up → On the way → Delivered.
  int get step => switch (status) {
        'unassigned' => 0,
        'assigned' || 'accepted' => 1,
        'picked_up' => 2,
        'delivered' => 4,
        _ => 3,
      };
}
