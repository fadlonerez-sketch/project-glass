#version 440
// Project Glass -- Liquid Glass material (v2).
//
// One pass draws the whole surface: a two-layer shadow outside the shape, and inside it a slab of glass
// with a rounded (circular-profile) bevel:
//
//   * the backdrop is refracted through the bevel (real lensing of the real backdrop texture: the
//     wallpaper as Windows lays it out), blurred with a rotated 9-tap kernel over the mip chain, and split
//     slightly by wavelength at the rim (chromatic dispersion, leaning towards the accent hue);
//   * the glass body absorbs light: optionally tinted by the accent colour (thicker = richer), with an
//     internal top-to-bottom gradient;
//   * light reflects: Fresnel brightening at grazing angles, a key rim highlight from the upper left, a thin
//     glint just inside the top edge, a faint internal reflection on the opposite rim, a soft caustic where
//     light focuses along the bottom inner edge, and an optional pointer light that follows the cursor;
//   * readability is protected adaptively: where the backdrop is too bright (dark theme) or too dark
//     (light theme) for the text on top, the tint quietly thickens.
//
// Every glass effect is scaled by `intensity` (the master control). At intensity 0 the result is exactly
// the base material (tint at full opacity + hairline + shadow); blur/refraction/shine keep their values.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 itemSize;        // logical px of the whole item (shape + shadow margin)
    vec4 shapeRect;       // x, y, w, h of the glass shape inside the item (logical px)
    float radius;         // corner radius (logical px)
    float intensity;      // master 0..1
    float blur;           // 0..1
    float refraction;     // 0..1
    float shine;          // 0..1
    float tintOpacity;    // base material opacity when intensity = 1 (0..1)
    vec4 tintColor;       // base material colour
    vec4 backdropRect;    // where this item sits in the backdrop texture: uv x, y, w, h
    float dpr;            // device pixel ratio
    float shadowStrength; // 0..1
    float darkMode;       // 0 light, 1 dark
    float backdropLod;    // mip levels available (for the blur ceiling)
    vec4 accentGlow;      // optional accent rim glow (rgb, strength in .a)
    float edge;           // edge treatment 0..1: hairline strength and rim definition
    float rimTop;         // 1 = draw the hairline on all sides; 0 = only where the shape is inside the item
    vec4 accentTint;      // accent colour (rgb) and how strongly it tints the glass body (.a, 0..1)
    vec4 pointerLight;    // cursor position in item px (xy) and its strength (z, 0 = off)
    float frost;          // 0 clear .. 1 frosted: diffuses highlights and lifts the body
};

layout(binding = 1) uniform sampler2D backdrop;

float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + vec2(r);
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// Rotated 9-tap kernel over one mip level: smooth, without the blockiness of a raw mip lookup.
vec3 blurAt(vec2 uv, float lod, vec2 texel) {
    vec2 o = texel * exp2(lod) * 0.85;
    vec3 c = textureLod(backdrop, uv, lod).rgb * 0.20;
    c += textureLod(backdrop, uv + o * vec2( 0.95,  0.31), lod).rgb * 0.10;
    c += textureLod(backdrop, uv + o * vec2(-0.31,  0.95), lod).rgb * 0.10;
    c += textureLod(backdrop, uv + o * vec2(-0.95, -0.31), lod).rgb * 0.10;
    c += textureLod(backdrop, uv + o * vec2( 0.31, -0.95), lod).rgb * 0.10;
    c += textureLod(backdrop, uv + o * vec2( 1.40, -1.05), lod).rgb * 0.10;
    c += textureLod(backdrop, uv + o * vec2( 1.05,  1.40), lod).rgb * 0.10;
    c += textureLod(backdrop, uv + o * vec2(-1.40,  1.05), lod).rgb * 0.10;
    c += textureLod(backdrop, uv + o * vec2(-1.05, -1.40), lod).rgb * 0.10;
    return c;
}

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

void main() {
    vec2 px = qt_TexCoord0 * itemSize;
    vec2 half_ = shapeRect.zw * 0.5;
    vec2 center = shapeRect.xy + half_;
    vec2 p = px - center;
    float r = min(radius, min(half_.x, half_.y));
    float d = sdRoundBox(p, half_, r);
    float aa = 1.0 / max(dpr, 1.0);

    // ---- shadow (outside the shape): a wide ambient layer and a tighter key layer ------------
    float ambientBlur = 22.0 + 14.0 * shadowStrength;
    float keyBlur = 7.0 + 5.0 * shadowStrength;
    float dA = sdRoundBox(p - vec2(0.0, 7.0 * shadowStrength + 2.0), half_, r);
    float dK = sdRoundBox(p - vec2(0.0, 2.0), half_, r);
    float shadowA = (darkMode > 0.5 ? 0.42 : 0.15) * pow(clamp(1.0 - dA / ambientBlur, 0.0, 1.0), 2.4)
                  + (darkMode > 0.5 ? 0.30 : 0.10) * pow(clamp(1.0 - dK / keyBlur, 0.0, 1.0), 2.0);
    shadowA *= shadowStrength;
    float contact = shadowStrength * 0.10 * pow(clamp(1.0 - d / 2.5, 0.0, 1.0), 2.0);
    shadowA = clamp(max(shadowA, contact), 0.0, 0.85);

    float inside = clamp(0.5 - d / aa, 0.0, 1.0);
    if (inside <= 0.0) {
        fragColor = vec4(0.0, 0.0, 0.0, shadowA) * qt_Opacity;
        return;
    }

    // ---- geometry of the slab --------------------------------------------------------------
    float e = 0.75;
    vec2 grad = vec2(sdRoundBox(p + vec2(e, 0.0), half_, r) - sdRoundBox(p - vec2(e, 0.0), half_, r),
                     sdRoundBox(p + vec2(0.0, e), half_, r) - sdRoundBox(p - vec2(0.0, e), half_, r));
    vec2 n = length(grad) > 1e-4 ? normalize(grad) : vec2(0.0);

    float bevel = max(min(max(r, 6.0) * 1.1, min(half_.x, half_.y)), 1.0);
    float depth = clamp(-d / bevel, 0.0, 1.0);           // 0 at the rim, 1 on the flat top
    float x = 1.0 - depth;                                // distance into the bevel from the top
    // Circular bevel profile: height h = sqrt(1 - x^2); its slope steepens sharply towards the rim.
    float slope = x * x / sqrt(max(1.0 - x * x * 0.92, 0.08));
    slope = min(slope, 3.0);
    vec2 uvPerPx = backdropRect.zw / itemSize;
    vec2 texel = uvPerPx / max(dpr, 1.0);
    float yN = clamp((px.y - shapeRect.y) / max(shapeRect.w, 1.0), 0.0, 1.0);

    // ---- refraction: rays through the bevel bend towards the centre --------------------------
    float refr = refraction * intensity;
    vec2 dispPx = -n * slope * bevel * 0.55 * refr;       // edge lensing (real backdrop pixels)
    dispPx += -p * 0.04 * refr * depth;                    // slight magnification of the flat top
    vec2 uv = backdropRect.xy + qt_TexCoord0 * backdropRect.zw;

    float lod = clamp(blur * intensity * min(backdropLod, 6.0), 0.0, 8.0);
    float disp = (0.06 + 0.10 * x * x) * refr;             // dispersion grows towards the rim
    vec3 glass;
    glass.r = blurAt(uv + dispPx * (1.0 + disp) * uvPerPx, lod, texel).r;
    glass.g = blurAt(uv + dispPx * uvPerPx, lod, texel).g;
    glass.b = blurAt(uv + dispPx * (1.0 - disp) * uvPerPx, lod, texel).b;

    // Vibrancy: blurred backdrops look washed out without a saturation lift.
    float l0 = luma(glass);
    glass = clamp(mix(vec3(l0), glass, 1.0 + 0.40 * intensity), 0.0, 1.0);

    // ---- the glass body: absorption, accent tint and internal gradient ----------------------
    vec3 accent = accentTint.rgb;
    float tintK = accentTint.a * intensity;
    // Thicker glass absorbs more: the accent colour is richest in the body, clearer at the rim.
    vec3 absorb = mix(vec3(1.0), clamp(accent * 1.35 + 0.18, 0.0, 1.0), tintK * (0.30 + 0.40 * depth));
    glass *= absorb;

    vec3 tint = tintColor.rgb;
    vec3 accentBody = darkMode > 0.5 ? mix(tint, accent * 0.55, 0.85) : mix(tint, mix(accent, vec3(1.0), 0.55), 0.85);
    tint = mix(tint, accentBody, tintK * 0.70);
    float tintA = mix(1.0, tintOpacity, intensity);

    // Adaptive readability: thicken the tint where the backdrop fights the text colour (bright backdrops under light
    // text in Dark, dark or saturated backdrops under dark text in Light). Calm backdrops keep the glass clear.
    float lb = luma(glass);
    float sat = max(glass.r, max(glass.g, glass.b)) - min(glass.r, min(glass.g, glass.b));
    float fight = darkMode > 0.5 ? smoothstep(0.22, 0.70, lb) : max(smoothstep(0.85, 0.35, lb), smoothstep(0.25, 0.65, sat) * 0.8);
    tintA = mix(tintA, min(1.0, tintA + 0.38), fight * intensity);

    vec3 col = mix(glass, tint, tintA);
    // internal gradient: light enters from above
    col += vec3(1.0) * mix(0.045, -0.030, yN) * intensity * (0.6 + 0.4 * frost);
    // frost scatters: lifts the body slightly towards the tint's luminance
    col = mix(col, vec3(luma(col)) * 0.15 + col * 0.85, frost * 0.25 * intensity);

    // ---- light ---------------------------------------------------------------------------
    float sh = shine * intensity;
    vec2 L = normalize(vec2(-0.55, -1.0));
    float facing = dot(n, L);
    float sharp = mix(6.0, 3.0, frost);
    // Fresnel: grazing angles at the rim reflect more of the (bright) environment.
    float fresnel = pow(x, 3.0) * (0.10 + 0.08 * (1.0 - frost));
    col = mix(col, mix(vec3(1.0), accent, 0.18 * tintK), fresnel * sh);
    // key rim highlight (upper left) and the internal reflection on the opposite rim
    float key = pow(x, sharp) * max(facing, 0.0);
    float back = pow(x, sharp + 1.0) * max(-facing, 0.0);
    col += vec3(1.0) * key * 0.85 * sh;
    col += mix(vec3(1.0), accent, 0.35) * back * 0.22 * sh;
    // a thin glint just inside the top edge
    float glintBand = clamp(1.0 - abs(d + 1.6) / 1.1, 0.0, 1.0) * smoothstep(0.15, -0.85, n.y);
    col += vec3(1.0) * glintBand * 0.30 * sh * (1.0 - 0.6 * frost);
    // top sheen
    col += vec3(1.0) * (1.0 - smoothstep(0.0, 0.5, yN)) * 0.05 * sh;
    // caustic: light focused through the slab gathers along the bottom inner edge
    float causticBand = exp(-pow((-d - bevel * 0.45) / max(bevel * 0.30, 1.0), 2.0)) * smoothstep(-0.2, 0.9, n.y);
    col += mix(vec3(1.0), accent, 0.5 * tintK + 0.15) * causticBand * 0.10 * sh;
    // dispersion fringe leaning towards the accent hue, only at the very rim
    col += accent * pow(x, 4.0) * 0.10 * refr * (0.4 + tintK);
    // pointer light: the edges near the cursor catch light (dynamic, only while hovered)
    if (pointerLight.z > 0.001) {
        float dist = length(px - pointerLight.xy);
        float reach = max(60.0, min(shapeRect.z, shapeRect.w) * 1.4);
        float near_ = exp(-pow(dist / reach, 2.0));
        col += vec3(1.0) * near_ * (0.04 + 0.30 * pow(x, 3.0)) * pointerLight.z * sh;
    }

    // ---- hairline edge (part of the base material, always present) --------------------------
    float hair = clamp(1.0 - abs(d + 0.6) / (0.9 * aa + 0.4), 0.0, 1.0);
    float topBias = 0.5 + 0.5 * clamp(-n.y, -1.0, 1.0);
    float hairA = (darkMode > 0.5 ? mix(0.10, 0.28, topBias) : mix(0.30, 0.78, topBias)) * clamp(edge * 1.5, 0.0, 1.6);
    col = mix(col, vec3(1.0), clamp(hair * hairA, 0.0, 1.0));
    if (darkMode < 0.5) {
        float outer = clamp(1.0 - abs(d + 0.15) / (0.8 * aa + 0.3), 0.0, 1.0);
        col = mix(col, vec3(0.0), outer * 0.10 * clamp(edge * 1.5, 0.0, 1.6));
    }

    // ---- optional accent glow along the rim (Garvis activity, focus) -------------------------
    col += accentGlow.rgb * accentGlow.a * pow(x, 3.0) * 0.6;

    float a = inside;
    vec4 surface = vec4(clamp(col, 0.0, 1.0) * a, a);
    fragColor = (surface + vec4(0.0, 0.0, 0.0, shadowA) * (1.0 - a)) * qt_Opacity;
}
