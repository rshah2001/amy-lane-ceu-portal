class PortalUser {
  PortalUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
  });

  factory PortalUser.fromJson(Map<String, dynamic> json) => PortalUser(
        id: json['id'] as int,
        email: json['email'] as String,
        fullName: json['full_name'] as String,
        role: json['role'] as String,
      );

  final int id;
  final String email;
  final String fullName;
  final String role;

  bool get isAdmin => role == 'admin';
}

class TrainingEvent {
  TrainingEvent({
    required this.id,
    required this.title,
    required this.eventDate,
    required this.ceuHours,
    required this.status,
    this.description,
    this.location,
    this.presenterName,
    this.courseInstructor,
    this.eventType = 'lunch_and_learn',
    this.postTestUrl,
    this.testMode = 'external',
    this.testToken,
    this.testQuestions = const [],
    this.surveyMode = 'internal',
    this.surveyRequired = false,
    this.externalSurveyUrl,
    this.surveyToken,
    this.certificateTitle = 'Certificate of Completion',
    this.certificateTemplatePath,
    this.certificateTemplateVersion = 1,
    this.assignedPresenterId,
    this.assignedPresenterName,
  });

  factory TrainingEvent.fromJson(Map<String, dynamic> json) => TrainingEvent(
        id: json['id'] as int,
        title: json['title'] as String,
        eventDate: DateTime.parse(json['event_date'] as String),
        ceuHours: double.parse(json['ceu_hours'].toString()),
        status: json['status'] as String,
        description: json['description'] as String?,
        location: json['location'] as String?,
        presenterName: json['presenter_name'] as String?,
        courseInstructor: json['course_instructor'] as String?,
        eventType: json['event_type'] as String? ?? 'lunch_and_learn',
        postTestUrl: json['post_test_url'] as String?,
        testMode: json['test_mode'] as String? ?? 'external',
        testToken: json['test_token'] as String?,
        testQuestions: (json['test_questions'] as List?)?.cast<Map<String, dynamic>>() ?? const [],
        surveyMode: json['survey_mode'] as String? ?? 'internal',
        surveyRequired: json['survey_required'] as bool? ?? false,
        externalSurveyUrl: json['external_survey_url'] as String?,
        surveyToken: json['survey_token'] as String?,
        certificateTitle: json['certificate_title'] as String? ?? 'Certificate of Completion',
        certificateTemplatePath: json['certificate_template_path'] as String?,
        certificateTemplateVersion: json['certificate_template_version'] as int? ?? 1,
        assignedPresenterId: json['assigned_presenter_id'] as int?,
        assignedPresenterName: json['assigned_presenter_name'] as String?,
      );

  final int id;
  final String title;
  final DateTime eventDate;
  final double ceuHours;
  final String status;
  final String? description;
  final String? location;
  final String? presenterName;
  final String? courseInstructor;
  final String eventType;
  final String? postTestUrl;
  final String testMode;
  final String? testToken;
  final List<Map<String, dynamic>> testQuestions;
  final String surveyMode;
  final bool surveyRequired;
  final String? externalSurveyUrl;
  final String? surveyToken;
  final String certificateTitle;
  final String? certificateTemplatePath;
  final int certificateTemplateVersion;
  final int? assignedPresenterId;
  final String? assignedPresenterName;
}

class DashboardStats {
  DashboardStats({
    required this.totalEvents,
    required this.upcomingEvents,
    required this.pendingReviews,
    required this.certificatesSent,
    required this.complianceRate,
  });

  factory DashboardStats.fromJson(Map<String, dynamic> json) => DashboardStats(
        totalEvents: json['total_events'] as int,
        upcomingEvents: json['upcoming_events'] as int,
        pendingReviews: json['pending_reviews'] as int,
        certificatesSent: json['certificates_sent'] as int,
        complianceRate: (json['compliance_rate'] as num).toDouble(),
      );

  final int totalEvents;
  final int upcomingEvents;
  final int pendingReviews;
  final int certificatesSent;
  final double complianceRate;
}

class EventSummary {
  EventSummary({
    required this.totalAttendees,
    required this.registered,
    required this.attended,
    required this.testPassed,
    required this.surveyCompleted,
    required this.eligible,
    required this.approved,
    required this.certificatesGenerated,
    required this.certificatesSent,
    required this.complianceRate,
  });

  factory EventSummary.fromJson(Map<String, dynamic> json) => EventSummary(
        totalAttendees: json['total_attendees'] as int,
        registered: json['registered'] as int,
        attended: json['attended'] as int,
        testPassed: json['test_passed'] as int,
        surveyCompleted: json['survey_completed'] as int,
        eligible: json['eligible'] as int,
        approved: json['approved'] as int,
        certificatesGenerated: json['certificates_generated'] as int,
        certificatesSent: json['certificates_sent'] as int,
        complianceRate: (json['compliance_rate'] as num).toDouble(),
      );

  final int totalAttendees;
  final int registered;
  final int attended;
  final int testPassed;
  final int surveyCompleted;
  final int eligible;
  final int approved;
  final int certificatesGenerated;
  final int certificatesSent;
  final double complianceRate;
}

class ChartBucket {
  ChartBucket(this.label, this.value);
  factory ChartBucket.fromJson(Map<String, dynamic> json) =>
      ChartBucket(json['label'] as String, json['value'] as int);
  final String label;
  final int value;
}

class EventCompliancePoint {
  EventCompliancePoint(this.title, this.eligible, this.total);
  factory EventCompliancePoint.fromJson(Map<String, dynamic> json) => EventCompliancePoint(
        json['title'] as String,
        json['eligible'] as int,
        json['total'] as int,
      );
  final String title;
  final int eligible;
  final int total;
}

class DashboardCharts {
  DashboardCharts({
    required this.scoreDistribution,
    required this.eventsCompliance,
    required this.monthlyCertificates,
  });

  factory DashboardCharts.fromJson(Map<String, dynamic> json) => DashboardCharts(
        scoreDistribution:
            (json['score_distribution'] as List).map((e) => ChartBucket.fromJson(e as Map<String, dynamic>)).toList(),
        eventsCompliance: (json['events_compliance'] as List)
            .map((e) => EventCompliancePoint.fromJson(e as Map<String, dynamic>))
            .toList(),
        monthlyCertificates:
            (json['monthly_certificates'] as List).map((e) => ChartBucket.fromJson(e as Map<String, dynamic>)).toList(),
      );

  final List<ChartBucket> scoreDistribution;
  final List<EventCompliancePoint> eventsCompliance;
  final List<ChartBucket> monthlyCertificates;
}

class ComplianceRecord {
  ComplianceRecord({
    required this.id,
    required this.fullName,
    required this.registered,
    required this.attended,
    required this.testCompleted,
    required this.surveyCompleted,
    required this.validEmail,
    required this.eligible,
    required this.approved,
    required this.reasons,
    this.lifecycleStatus = 'pending',
    this.email,
    this.company,
    this.testScore,
    this.certificateId,
    this.certificateNumber,
    this.certificateSentAt,
    this.certificateDownloadedAt,
  });

  factory ComplianceRecord.fromJson(Map<String, dynamic> json) => ComplianceRecord(
        id: json['id'] as int,
        fullName: json['full_name'] as String,
        email: json['email'] as String?,
        company: json['company'] as String?,
        registered: json['registered'] as bool,
        attended: json['attended'] as bool,
        testCompleted: json['test_completed'] as bool,
        testScore: (json['test_score'] as num?)?.toDouble(),
        surveyCompleted: json['survey_completed'] as bool,
        validEmail: json['has_valid_email'] as bool,
        eligible: json['eligible'] as bool,
        approved: json['approved'] as bool,
        reasons: (json['eligibility_reasons'] as List).cast<String>(),
        lifecycleStatus: json['lifecycle_status'] as String? ?? 'pending',
        certificateId: json['certificate_id'] as int?,
        certificateNumber: json['certificate_number'] as String?,
        certificateSentAt: json['certificate_sent_at'] == null
            ? null
            : DateTime.parse(json['certificate_sent_at'] as String),
        certificateDownloadedAt: json['certificate_downloaded_at'] == null
            ? null
            : DateTime.parse(json['certificate_downloaded_at'] as String),
      );

  final int id;
  final String fullName;
  final String? email;
  final String? company;
  final bool registered;
  final bool attended;
  final bool testCompleted;
  final double? testScore;
  final bool surveyCompleted;
  final bool validEmail;
  final bool eligible;
  final bool approved;
  final List<String> reasons;
  final String lifecycleStatus;
  final int? certificateId;
  final String? certificateNumber;
  final DateTime? certificateSentAt;
  final DateTime? certificateDownloadedAt;
}
