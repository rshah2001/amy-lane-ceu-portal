import 'package:flutter/material.dart';

/// The portal's design system: one type scale, one colour vocabulary, one
/// spacing grid.
///
/// Every colour here carries its measured WCAG 2.1 contrast ratio in a comment.
/// That is not decoration — NMEDA's members build vehicle modifications for
/// drivers with disabilities, and the public check-in / post-test / survey /
/// verification pages are used by those drivers directly. A ratio that drifts
/// below its noted minimum is a regression, not a style preference.
///
/// Ratios were computed against the three surfaces text and outlines actually
/// land on: white cards `#FFFFFF`, the page canvas `#F5F7FA`, and the tinted
/// table/card fill `#F7F9FB`. The tightest of the three is the one quoted.

// ─────────────────────────────────────────────────────────────────────────────
// Brand constants
//
// These five stay top-level because a dozen files reference them directly for
// non-themed uses (chart series, avatar fills, the login hero). Everything
// *semantic* — success, danger, muted text, borders — lives in [PortalColors]
// so it can be swapped in one place.
// ─────────────────────────────────────────────────────────────────────────────

/// Primary brand colour. 13.13:1 on white, 12.23:1 on canvas.
const navy = Color(0xFF17324D);

/// Secondary brand colour. 4.86:1 on white, 4.53:1 on canvas — nudged one step
/// darker than the original `#177E89` (4.47:1 on canvas) so it clears AA for
/// body text on every surface, not just white.
const teal = Color(0xFF167D88);

/// Accent gold. Darkened from `#B58A3B`, which measured **2.94:1 on canvas** —
/// a straight AA failure everywhere it appeared (the "Pending review" stat
/// card, the System Health "Certificates sent" card). Now **5.35:1 on white,
/// 4.99:1 on canvas**.
const gold = Color(0xFF8A6420);

/// Page background behind every card.
const canvas = Color(0xFFF5F7FA);

/// Every card outline, input outline, outlined-button border and divider.
/// Darkened from `#DCE3EA`, which measured **1.29:1 on white** — far under the
/// 3:1 that WCAG 1.4.11 requires for the boundary of a UI component. Now
/// **3.33:1 on white, 3.10:1 on canvas, 3.15:1 on the tinted fill**.
///
/// This is deliberately a single token rather than a strong/subtle pair: in a
/// dense compliance table the row separators are load-bearing for anyone with
/// low vision, so they get the same floor as the input outlines.
const border = Color(0xFF838E9C);

// ─────────────────────────────────────────────────────────────────────────────
// Spacing and radii
// ─────────────────────────────────────────────────────────────────────────────

/// 4pt spacing grid. Replaces the 25 ad-hoc gap values the layout used to mix
/// (2, 3, 5, 7, 10, 14, 18, 21, 22, 26, 42, 56 …), which made no two cards line
/// up on their internal rhythm.
abstract final class Space {
  /// 4 — hairline gaps inside a single line of content.
  static const xxs = 4.0;

  /// 8 — between tightly related elements (icon and its label).
  static const xs = 8.0;

  /// 12 — between sibling controls in a row.
  static const sm = 12.0;

  /// 16 — the default gap between form fields and between cards.
  static const md = 16.0;

  /// 20 — standard card padding.
  static const lg = 20.0;

  /// 24 — page padding, and the gap between major page sections.
  static const xl = 24.0;

  /// 32 — between unrelated blocks.
  static const xxl = 32.0;

  /// 48 — hero/empty-state breathing room.
  static const xxxl = 48.0;
}

/// Three radii instead of the five the app had grown (4/6/8/12/14).
abstract final class Radii {
  /// 6 — controls: inputs, buttons, nav tiles.
  static const sm = 6.0;

  /// 8 — containers: cards, alerts, tinted panels.
  static const md = 8.0;

  /// 999 — fully rounded: badges, chips, count pills.
  static const pill = 999.0;
}

/// The smallest square any pointer target is allowed to occupy. WCAG 2.5.5
/// asks for 44×44 CSS px; Flutter's own [kMinInteractiveDimension] is 48, which
/// every `IconButton` already honours. This constant is for the hand-built
/// tap targets that don't.
const minTapTarget = 44.0;

/// One content column width for every page inside the app shell. The app used
/// to mix 1480 / 1100 / 920 / 900, so the column visibly jumped width on almost
/// every navigation.
const maxContentWidth = 1480.0;

/// Narrower inner width for form-shaped content. A 15-field form stretched to
/// [maxContentWidth] puts a 1400px-wide text input on screen, which is
/// unreadable — so the *page column* stays fixed and the *form* is constrained
/// inside it.
const maxFormWidth = 920.0;

/// Reading width for the standalone public pages (check-in, post-test, survey,
/// certificate verification). These are not in the app shell and have no
/// sidebar to line up with, so they keep a measure tuned for prose and single
/// column forms rather than the dashboard grid.
const maxPublicWidth = 720.0;

// ─────────────────────────────────────────────────────────────────────────────
// Semantic colours
// ─────────────────────────────────────────────────────────────────────────────

/// Semantic colour tokens, reached via `Theme.of(context).portal`.
///
/// Consolidates what used to be 139 hardcoded hex literals across 30 distinct
/// values — including **three different greens** for "success"
/// (`#248A52`, `#12805C`, `#176B3A`) and **four muted greys**
/// (`#667085`, `#98A2B3`, `#475467`, `#344054`) — into one value per role.
@immutable
class PortalColors extends ThemeExtension<PortalColors> {
  const PortalColors({
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.outline,
    required this.surface,
    required this.surfaceSubtle,
    required this.surfaceSunken,
    required this.success,
    required this.successSurface,
    required this.warning,
    required this.warningSurface,
    required this.danger,
    required this.dangerSurface,
    required this.dangerOutline,
    required this.info,
    required this.infoSurface,
    required this.neutral,
    required this.neutralSurface,
    required this.accent,
    required this.accentAlt,
    required this.navSurface,
    required this.navSelected,
    required this.navAccent,
    required this.navOutline,
    required this.onNavMuted,
    required this.onNavSubtle,
  });

  /// Body copy and headings. 14.70:1 on white.
  final Color textPrimary;

  /// Supporting copy — subtitles, descriptions, helper text. 6.39:1 on white,
  /// 5.96:1 on canvas. Absorbs the old `#667085` and `#475467`.
  final Color textSecondary;

  /// Captions, timestamps, and meaning-bearing placeholder icons — the 11–12px
  /// tier. 4.97:1 on white, 4.64:1 on canvas.
  ///
  /// This replaces `#98A2B3`, which measured **2.58:1** and was carrying 11px
  /// notification timestamps. Small text gets no AA discount, so the tertiary
  /// tier cannot sit much lighter than this and still be readable.
  final Color textTertiary;

  /// Same value as the top-level [border]; exposed here so widgets that already
  /// read the extension don't need a second import. 3.33:1 on white.
  final Color outline;

  /// Card and dialog fill.
  final Color surface;

  /// Tinted fill for nested cards, table heading rows, and inset panels.
  /// Absorbs the old `#F7FAFC`, `#F7F9FB` and `#F4F6F8`.
  final Color surfaceSubtle;

  /// Recessed fill for neutral chips and inactive avatars.
  final Color surfaceSunken;

  /// Requirement met, certificate delivered, template saved.
  /// 5.11:1 on white, 4.76:1 on canvas, 4.55:1 on [successSurface].
  final Color success;
  final Color successSurface;

  /// Needs attention but nothing is broken — unread parse errors, an event
  /// awaiting review. 5.43:1 on white, 4.95:1 on [warningSurface].
  final Color warning;
  final Color warningSurface;

  /// Destructive or failed. 6.57:1 on white, 5.76:1 on [dangerSurface].
  final Color danger;
  final Color dangerSurface;
  final Color dangerOutline;

  /// Informational, and the colour of in-page links. 7.22:1 on white.
  final Color info;
  final Color infoSurface;

  /// "No state yet" — not-uploaded, unassigned. 7.69:1 on white.
  final Color neutral;
  final Color neutralSurface;

  /// Brand accent for figures that are neither good nor bad (same as [gold]).
  final Color accent;

  /// Second accent, for the fifth and sixth series in a stat row where reusing
  /// navy/teal/gold would imply a meaning that isn't there. 4.94:1 on white.
  final Color accentAlt;

  /// Sidebar background (same as [navy]).
  final Color navSurface;

  /// Fill of the selected sidebar tile. 2.01:1 against [navSurface], with white
  /// label text still at 6.53:1.
  ///
  /// A fill light enough to reach 3:1 against the navy sidebar would drop its
  /// own white label below 4.5:1 — the two requirements are mutually exclusive
  /// on a dark surface. So the fill is a supporting cue only and [navAccent]
  /// carries the 1.4.11 obligation. See [navAccent].
  final Color navSelected;

  /// The left accent bar on the selected sidebar tile: **8.02:1 against the
  /// navy sidebar, 3.99:1 against [navSelected]**.
  ///
  /// This is the actual state indicator. The old design signalled the current
  /// page *only* by a `#294761` tile at **1.44:1** — invisible to a low-vision
  /// user, and colour-only besides. The bar plus a bold label means the current
  /// page is identifiable by position, weight, and contrast, not hue alone.
  final Color navAccent;

  /// Sidebar rules. 2.24:1 on navy — decorative grouping, not a component
  /// boundary, so 1.4.11's 3:1 doesn't apply; still lifted from 1.56:1.
  final Color navOutline;

  /// Muted label on the navy sidebar (the role caption). 6.98:1 on navy.
  final Color onNavMuted;

  /// Body copy on the navy login panel. 9.97:1 on navy.
  final Color onNavSubtle;

  static const light = PortalColors(
    textPrimary: Color(0xFF1D2939),
    textSecondary: Color(0xFF55606E),
    textTertiary: Color(0xFF667085),
    outline: border,
    surface: Colors.white,
    surfaceSubtle: Color(0xFFF7F9FB),
    surfaceSunken: Color(0xFFF0F2F5),
    success: Color(0xFF187E46),
    successSurface: Color(0xFFE8F5EE),
    warning: Color(0xFFB54708),
    warningSurface: Color(0xFFFFF4D6),
    danger: Color(0xFFB42318),
    dangerSurface: Color(0xFFFEECEB),
    dangerOutline: Color(0xFFF4B4AE),
    info: Color(0xFF245B85),
    infoSurface: Color(0xFFE9F2FA),
    neutral: Color(0xFF475467),
    neutralSurface: Color(0xFFF0F2F5),
    accent: gold,
    accentAlt: Color(0xFF5F6CAF),
    navSurface: navy,
    navSelected: Color(0xFF3A6183),
    navAccent: Color(0xFFEDC65C),
    navOutline: Color(0xFF4A6787),
    onNavMuted: Color(0xFFAAC0D1),
    onNavSubtle: Color(0xFFD6E2EC),
  );

  @override
  PortalColors copyWith({
    Color? textPrimary,
    Color? textSecondary,
    Color? textTertiary,
    Color? outline,
    Color? surface,
    Color? surfaceSubtle,
    Color? surfaceSunken,
    Color? success,
    Color? successSurface,
    Color? warning,
    Color? warningSurface,
    Color? danger,
    Color? dangerSurface,
    Color? dangerOutline,
    Color? info,
    Color? infoSurface,
    Color? neutral,
    Color? neutralSurface,
    Color? accent,
    Color? accentAlt,
    Color? navSurface,
    Color? navSelected,
    Color? navAccent,
    Color? navOutline,
    Color? onNavMuted,
    Color? onNavSubtle,
  }) {
    return PortalColors(
      textPrimary: textPrimary ?? this.textPrimary,
      textSecondary: textSecondary ?? this.textSecondary,
      textTertiary: textTertiary ?? this.textTertiary,
      outline: outline ?? this.outline,
      surface: surface ?? this.surface,
      surfaceSubtle: surfaceSubtle ?? this.surfaceSubtle,
      surfaceSunken: surfaceSunken ?? this.surfaceSunken,
      success: success ?? this.success,
      successSurface: successSurface ?? this.successSurface,
      warning: warning ?? this.warning,
      warningSurface: warningSurface ?? this.warningSurface,
      danger: danger ?? this.danger,
      dangerSurface: dangerSurface ?? this.dangerSurface,
      dangerOutline: dangerOutline ?? this.dangerOutline,
      info: info ?? this.info,
      infoSurface: infoSurface ?? this.infoSurface,
      neutral: neutral ?? this.neutral,
      neutralSurface: neutralSurface ?? this.neutralSurface,
      accent: accent ?? this.accent,
      accentAlt: accentAlt ?? this.accentAlt,
      navSurface: navSurface ?? this.navSurface,
      navSelected: navSelected ?? this.navSelected,
      navAccent: navAccent ?? this.navAccent,
      navOutline: navOutline ?? this.navOutline,
      onNavMuted: onNavMuted ?? this.onNavMuted,
      onNavSubtle: onNavSubtle ?? this.onNavSubtle,
    );
  }

  @override
  PortalColors lerp(ThemeExtension<PortalColors>? other, double t) {
    if (other is! PortalColors) return this;
    return PortalColors(
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      textTertiary: Color.lerp(textTertiary, other.textTertiary, t)!,
      outline: Color.lerp(outline, other.outline, t)!,
      surface: Color.lerp(surface, other.surface, t)!,
      surfaceSubtle: Color.lerp(surfaceSubtle, other.surfaceSubtle, t)!,
      surfaceSunken: Color.lerp(surfaceSunken, other.surfaceSunken, t)!,
      success: Color.lerp(success, other.success, t)!,
      successSurface: Color.lerp(successSurface, other.successSurface, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      warningSurface: Color.lerp(warningSurface, other.warningSurface, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      dangerSurface: Color.lerp(dangerSurface, other.dangerSurface, t)!,
      dangerOutline: Color.lerp(dangerOutline, other.dangerOutline, t)!,
      info: Color.lerp(info, other.info, t)!,
      infoSurface: Color.lerp(infoSurface, other.infoSurface, t)!,
      neutral: Color.lerp(neutral, other.neutral, t)!,
      neutralSurface: Color.lerp(neutralSurface, other.neutralSurface, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      accentAlt: Color.lerp(accentAlt, other.accentAlt, t)!,
      navSurface: Color.lerp(navSurface, other.navSurface, t)!,
      navSelected: Color.lerp(navSelected, other.navSelected, t)!,
      navAccent: Color.lerp(navAccent, other.navAccent, t)!,
      navOutline: Color.lerp(navOutline, other.navOutline, t)!,
      onNavMuted: Color.lerp(onNavMuted, other.onNavMuted, t)!,
      onNavSubtle: Color.lerp(onNavSubtle, other.onNavSubtle, t)!,
    );
  }
}

/// `Theme.of(context).portal` — shorter than
/// `Theme.of(context).extension<PortalColors>()!` at 200-plus call sites, and
/// it cannot be null because [buildPortalTheme] always installs the extension.
extension PortalTheme on ThemeData {
  PortalColors get portal => extension<PortalColors>() ?? PortalColors.light;
}

// ─────────────────────────────────────────────────────────────────────────────
// Typography
// ─────────────────────────────────────────────────────────────────────────────

/// The OS UI font, in the order each platform wants it.
///
/// Deliberately *not* a downloaded webfont: a bundled or CDN font costs a
/// render-blocking fetch on top of a build that already ships several megabytes
/// before first paint, and this app's first screen for an attendee is a QR-code
/// landing page opened on conference-centre wifi. The system stack costs zero
/// bytes, paints immediately, and matches whatever the reader has already
/// configured — including any OS-level font size or weight adjustment they rely
/// on.
const _systemFont = 'system-ui';
const _systemFontFallback = <String>[
  '-apple-system',
  'BlinkMacSystemFont',
  'Segoe UI',
  'Roboto',
  'Helvetica Neue',
  'Arial',
  'sans-serif',
];

/// The type scale. Fifteen ad-hoc `fontSize:` literals (11, 12, 13, 14, 15, 16,
/// 17, 18, 20, 22, 24, 26, 30, 34, 36) collapse onto these fifteen named roles,
/// so "section heading" is one decision instead of four different numbers in
/// four different files.
TextTheme _buildTextTheme(PortalColors colors) {
  // Tighter tracking as size grows: at display sizes default spacing reads
  // loose, at caption sizes a little extra keeps 11px legible.
  TextStyle heading(double size, {double letterSpacing = -0.2}) => TextStyle(
        fontSize: size,
        height: 1.25,
        fontWeight: FontWeight.w700,
        letterSpacing: letterSpacing,
        color: colors.textPrimary,
      );

  TextStyle body(double size) => TextStyle(
        fontSize: size,
        height: 1.45,
        fontWeight: FontWeight.w400,
        color: colors.textPrimary,
      );

  TextStyle label(double size, {double letterSpacing = 0}) => TextStyle(
        fontSize: size,
        height: 1.35,
        fontWeight: FontWeight.w600,
        letterSpacing: letterSpacing,
        color: colors.textPrimary,
      );

  return TextTheme(
    // Display — the login hero and the post-test score. One per screen, at most.
    displayLarge: heading(36, letterSpacing: -0.7),
    displayMedium: heading(32, letterSpacing: -0.6),
    displaySmall: heading(28, letterSpacing: -0.5),

    // Headline — page titles and the headline of a public page.
    headlineLarge: heading(26, letterSpacing: -0.4),
    headlineMedium: heading(24, letterSpacing: -0.3),
    headlineSmall: heading(22, letterSpacing: -0.3),

    // Title — section and card headings.
    titleLarge: heading(20),
    titleMedium: heading(17, letterSpacing: -0.1),
    titleSmall: heading(15, letterSpacing: 0),

    // Body — running text. bodyMedium is the app-wide default.
    bodyLarge: body(16),
    bodyMedium: body(14),
    bodySmall: body(13),

    // Label — buttons, badges, table meta, timestamps.
    labelLarge: label(14),
    labelMedium: label(12, letterSpacing: 0.1),
    labelSmall: label(11, letterSpacing: 0.2),
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Theme
// ─────────────────────────────────────────────────────────────────────────────

ThemeData buildPortalTheme() {
  const colors = PortalColors.light;
  final text = _buildTextTheme(colors);

  // `ColorScheme.fromSeed` derives ~30 roles from the seed and the original
  // theme overrode only four of them. The unclaimed ones are what M3 hands to
  // SegmentedButton, FilterChip, Switch and the menu surfaces — which is why
  // the compliance eligibility filter rendered in a blue-lavender that appears
  // nowhere in the brand. Every role a component reaches for is pinned here.
  final scheme = ColorScheme.fromSeed(
    seedColor: navy,
    brightness: Brightness.light,
    primary: navy,
    secondary: teal,
    surface: Colors.white,
    error: colors.danger,
  ).copyWith(
    onPrimary: Colors.white,
    onSecondary: Colors.white,
    onSurface: colors.textPrimary,
    onError: Colors.white,
    // Selected SegmentedButton segments and selected FilterChips read from the
    // secondary container pair.
    secondaryContainer: colors.infoSurface,
    onSecondaryContainer: colors.info,
    primaryContainer: colors.infoSurface,
    onPrimaryContainer: navy,
    tertiary: colors.accent,
    onTertiary: Colors.white,
    tertiaryContainer: colors.warningSurface,
    onTertiaryContainer: colors.warning,
    errorContainer: colors.dangerSurface,
    onErrorContainer: colors.danger,
    // Secondary text inside Material components (helper text, unselected
    // segment labels, list subtitles).
    onSurfaceVariant: colors.textSecondary,
    outline: colors.outline,
    outlineVariant: colors.outline,
    surfaceContainerLowest: Colors.white,
    surfaceContainerLow: colors.surfaceSubtle,
    surfaceContainer: colors.surfaceSubtle,
    surfaceContainerHigh: colors.surfaceSunken,
    surfaceContainerHighest: colors.surfaceSunken,
  );

  const shapeSm = RoundedRectangleBorder(
    borderRadius: BorderRadius.all(Radius.circular(Radii.sm)),
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: canvas,
    fontFamily: _systemFont,
    fontFamilyFallback: _systemFontFallback,
    textTheme: text,
    primaryTextTheme: text,
    extensions: const [colors],

    // M3 tints surfaces with the primary colour as elevation rises. The portal
    // is a flat, outlined design, so every tint is switched off — otherwise
    // cards and dialogs pick up a navy wash that isn't in the palette.
    cardTheme: CardThemeData(
      color: colors.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.md)),
        side: BorderSide(color: border),
      ),
    ),

    dialogTheme: DialogThemeData(
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 3,
      titleTextStyle: text.titleLarge,
      contentTextStyle: text.bodyMedium,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.md)),
      ),
    ),

    appBarTheme: AppBarTheme(
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      foregroundColor: colors.textPrimary,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: text.titleMedium,
      shape: const Border(bottom: BorderSide(color: border)),
    ),

    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: colors.surface,
      border: const OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.sm)),
        borderSide: BorderSide(color: border),
      ),
      enabledBorder: const OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.sm)),
        borderSide: BorderSide(color: border),
      ),
      focusedBorder: const OutlineInputBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.sm)),
        borderSide: BorderSide(color: navy, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: const BorderRadius.all(Radius.circular(Radii.sm)),
        borderSide: BorderSide(color: colors.danger),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: const BorderRadius.all(Radius.circular(Radii.sm)),
        borderSide: BorderSide(color: colors.danger, width: 2),
      ),
      labelStyle: text.bodyMedium?.copyWith(color: colors.textSecondary),
      hintStyle: text.bodyMedium?.copyWith(color: colors.textTertiary),
      helperStyle: text.bodySmall?.copyWith(color: colors.textSecondary),
      errorStyle: text.bodySmall?.copyWith(color: colors.danger),
      prefixIconColor: colors.textSecondary,
      suffixIconColor: colors.textSecondary,
      contentPadding: const EdgeInsets.symmetric(
        horizontal: Space.md - 2,
        vertical: Space.md - 2,
      ),
    ),

    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        disabledBackgroundColor: colors.surfaceSunken,
        disabledForegroundColor: colors.textTertiary,
        elevation: 0,
        textStyle: text.labelLarge,
        shape: shapeSm,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
      ),
    ),

    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        textStyle: text.labelLarge,
        shape: shapeSm,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
      ),
    ),

    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: navy,
        disabledForegroundColor: colors.textTertiary,
        side: const BorderSide(color: border),
        textStyle: text.labelLarge,
        shape: shapeSm,
        padding: const EdgeInsets.symmetric(horizontal: Space.md, vertical: 14),
      ),
    ),

    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: colors.info,
        textStyle: text.labelLarge,
        shape: shapeSm,
      ),
    ),

    // Without this the selected segment fills with the seed-derived
    // `secondaryContainer` — the blue-lavender on the compliance eligibility
    // filter and the two Create Event mode pickers.
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        textStyle: WidgetStatePropertyAll(text.labelLarge),
        backgroundColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.disabled)) return colors.surfaceSunken;
          return states.contains(WidgetState.selected) ? colors.infoSurface : colors.surface;
        }),
        foregroundColor: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.disabled)) return colors.textTertiary;
          return states.contains(WidgetState.selected) ? navy : colors.textSecondary;
        }),
        iconColor: WidgetStateProperty.resolveWith((states) {
          return states.contains(WidgetState.selected) ? navy : colors.textSecondary;
        }),
        side: const WidgetStatePropertyAll(BorderSide(color: border)),
        shape: const WidgetStatePropertyAll(shapeSm),
      ),
    ),

    // Same story for FilterChip on the Audit Reports column picker.
    chipTheme: ChipThemeData(
      backgroundColor: colors.surface,
      selectedColor: colors.infoSurface,
      disabledColor: colors.surfaceSunken,
      checkmarkColor: navy,
      labelStyle: text.labelLarge?.copyWith(color: colors.textSecondary),
      secondaryLabelStyle: text.labelLarge?.copyWith(color: navy),
      side: const BorderSide(color: border),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.sm)),
      ),
      showCheckmark: true,
    ),

    switchTheme: SwitchThemeData(
      trackColor: WidgetStateProperty.resolveWith((states) {
        return states.contains(WidgetState.selected) ? colors.success : colors.surfaceSunken;
      }),
      thumbColor: WidgetStateProperty.resolveWith((states) {
        return states.contains(WidgetState.selected) ? Colors.white : colors.textSecondary;
      }),
      trackOutlineColor: WidgetStateProperty.resolveWith((states) {
        return states.contains(WidgetState.selected) ? colors.success : colors.outline;
      }),
    ),

    radioTheme: RadioThemeData(
      fillColor: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.disabled)) return colors.textTertiary;
        return states.contains(WidgetState.selected) ? navy : colors.textSecondary;
      }),
    ),

    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.disabled)) return colors.surfaceSunken;
        return states.contains(WidgetState.selected) ? navy : Colors.transparent;
      }),
      checkColor: const WidgetStatePropertyAll(Colors.white),
      side: const BorderSide(color: border, width: 1.5),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(3)),
      ),
    ),

    popupMenuTheme: PopupMenuThemeData(
      color: colors.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 3,
      textStyle: text.bodyMedium,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.md)),
        side: BorderSide(color: border),
      ),
    ),

    menuTheme: MenuThemeData(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(colors.surface),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
        elevation: const WidgetStatePropertyAll(3),
        shape: const WidgetStatePropertyAll(
          RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(Radii.md)),
            side: BorderSide(color: border),
          ),
        ),
      ),
    ),

    menuButtonTheme: MenuButtonThemeData(
      style: ButtonStyle(
        textStyle: WidgetStatePropertyAll(text.bodyMedium),
        foregroundColor: WidgetStatePropertyAll(colors.textPrimary),
        // Menu rows are a pointer target as much as buttons are, so they get
        // the same 44px floor rather than M3's tighter default.
        minimumSize: const WidgetStatePropertyAll(Size(0, minTapTarget)),
      ),
    ),

    dropdownMenuTheme: DropdownMenuThemeData(
      textStyle: text.bodyMedium,
      menuStyle: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(colors.surface),
        surfaceTintColor: const WidgetStatePropertyAll(Colors.transparent),
      ),
    ),

    listTileTheme: ListTileThemeData(
      iconColor: colors.textSecondary,
      textColor: colors.textPrimary,
      titleTextStyle: text.bodyMedium,
      subtitleTextStyle: text.bodySmall?.copyWith(color: colors.textSecondary),
      selectedColor: colors.textPrimary,
      shape: shapeSm,
    ),

    expansionTileTheme: ExpansionTileThemeData(
      iconColor: colors.textSecondary,
      collapsedIconColor: colors.textSecondary,
      textColor: colors.textPrimary,
      collapsedTextColor: colors.textPrimary,
      backgroundColor: Colors.transparent,
      collapsedBackgroundColor: Colors.transparent,
    ),

    dividerTheme: const DividerThemeData(color: border, thickness: 1, space: 1),

    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(
        color: colors.textPrimary,
        borderRadius: BorderRadius.circular(Radii.sm),
      ),
      textStyle: text.bodySmall?.copyWith(color: Colors.white),
      waitDuration: const Duration(milliseconds: 400),
    ),

    snackBarTheme: SnackBarThemeData(
      backgroundColor: colors.textPrimary,
      contentTextStyle: text.bodyMedium?.copyWith(color: Colors.white),
      actionTextColor: colors.navAccent,
      behavior: SnackBarBehavior.floating,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(Radii.md)),
      ),
    ),

    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: navy,
      linearTrackColor: colors.surfaceSunken,
      circularTrackColor: colors.surfaceSunken,
    ),

    datePickerTheme: DatePickerThemeData(
      backgroundColor: colors.surface,
      surfaceTintColor: Colors.transparent,
      headerBackgroundColor: navy,
      headerForegroundColor: Colors.white,
    ),

    dataTableTheme: DataTableThemeData(
      headingRowColor: WidgetStatePropertyAll(colors.surfaceSubtle),
      headingTextStyle: text.labelLarge?.copyWith(color: colors.textSecondary),
      dataTextStyle: text.bodyMedium,
      dividerThickness: 1,
      dataRowMinHeight: 48,
      // Unbounded on purpose. A fixed 72px cap clipped — and at ≥130% text
      // scale painted overflow stripes over — the compliance table's three-line
      // attendee cell, which is where the eligibility reasons live.
      dataRowMaxHeight: double.infinity,
    ),
  );
}
