import 'package:flutter_test/flutter_test.dart';

import 'package:ceu_compliance_portal/main.dart';
import 'package:ceu_compliance_portal/core/session.dart';

void main() {
  testWidgets('shows login screen when unauthenticated', (tester) async {
    await tester.pumpWidget(CeuPortalApp(session: SessionController()));

    expect(find.text('Sign in'), findsNWidgets(2));
    expect(find.text('Access your compliance workspace.'), findsOneWidget);
  });
}
