.pragma library
// The Glass motion language: one set of curves and durations, scaled by the user's animation speed.

function speed(theme) { return theme && theme.animation_speed ? theme.animation_speed : 1.0 }
function reduced(theme) { return theme && theme.reduce_motion }
function ms(theme, base) { return reduced(theme) ? Math.min(120, base) : Math.round(base / speed(theme)) }

// Spring presets per top-bar animation style (Qt SpringAnimation spring/damping/mass).
function spring(style) {
    if (style === "gentle") return { spring: 3.0, damping: 0.42, mass: 1.0 }
    if (style === "minimal") return { spring: 6.0, damping: 0.9, mass: 1.0 }
    return { spring: 3.6, damping: 0.30, mass: 1.0 }     // fluid: a little overshoot, like a droplet settling
}
