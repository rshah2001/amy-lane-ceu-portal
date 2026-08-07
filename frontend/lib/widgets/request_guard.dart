import 'package:flutter/widgets.dart';

/// Makes a page ignore the result of a request it has already superseded.
///
/// Every list page here reloads on a filter change, and the second request
/// routinely answers before the first: flip the event dropdown twice and the
/// slower, older response lands last and repaints the table with the wrong
/// roster. Nothing on screen says so — the dropdown still reads "Spring
/// session" over Autumn's attendees.
///
/// On the Certificate Center that is not a cosmetic problem. Its rows carry
/// Send and Resend buttons that email a real certificate to a real person, so a
/// list that repaints under the cursor between "read the name" and "press Send"
/// sends the wrong person's certificate.
///
/// Attendee Search had the only correct guard in the app, written inline; this
/// is that guard, factored out so the other four pages get the same one instead
/// of four near-copies.
///
/// ```dart
/// Future<void> load() async {
///   final request = beginRequest();
///   setState(() => rows = null);
///   final result = await api.get(...);
///   if (!request.isCurrent) return;   // a newer load() already started
///   setState(() => rows = result);
/// }
/// ```
mixin LatestRequest<T extends StatefulWidget> on State<T> {
  int _sequence = 0;

  /// Opens a request and invalidates every one still in flight.
  RequestToken beginRequest() => RequestToken._(this, ++_sequence);
}

/// Handle on one in-flight request, from [LatestRequest.beginRequest].
class RequestToken {
  RequestToken._(this._state, this._sequence);

  final LatestRequest _state;
  final int _sequence;

  /// Whether this request's result is still the one the page should show.
  ///
  /// Also false once the widget is gone, so it doubles as the `mounted` check
  /// every one of these call sites needs anyway — one condition to get right
  /// instead of two to forget.
  bool get isCurrent => _state.mounted && _sequence == _state._sequence;
}
