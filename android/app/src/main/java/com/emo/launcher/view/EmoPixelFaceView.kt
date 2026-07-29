package com.emo.launcher.view

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * EmoPixelFaceView — 100% Pure Native Kotlin Custom View.
 *
 * Renders EMO's iconic retro-futuristic pixelated LED face directly on the
 * Android Native Canvas with zero WebView/Chrome overhead.
 *
 * Features:
 *   - Crisp square LED dot-matrix grid with customizable glow colors
 *   - All 9 dynamic emotion states (IDLE, LISTENING, THINKING, SPEAKING,
 *     HAPPY, EXCITED, CONFUSED, SURPRISED, SAD, ANGRY)
 *   - Touch & Drag pupil eye-tracking
 *   - Automatic blinking and breathing animations
 */
class EmoPixelFaceView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    enum class State {
        IDLE, LISTENING, THINKING, SPEAKING,
        HAPPY, EXCITED, CONFUSED, CURIOUS,
        SURPRISED, SAD, ANGRY, ERROR
    }

    var currentState: State = State.IDLE
        set(value) {
            field = value
            updateGlowColor()
            invalidate()
        }

    private val ledPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        style = Paint.Style.FILL
    }

    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#00FFD1")
        style = Paint.Style.FILL
    }

    private var pupilX = 0f
    private var pupilY = 0f
    private var isBlinking = false
    private var animAngle = 0f

    init {
        // Enable hardware layer for smooth rendering
        setLayerType(LAYER_TYPE_HARDWARE, null)
        startAnimationLoop()
    }

    private fun updateGlowColor() {
        val hexColor = when (currentState) {
            State.HAPPY, State.EXCITED -> "#00FF88"
            State.CONFUSED, State.CURIOUS -> "#FFE600"
            State.SURPRISED -> "#FFFFFF"
            State.SAD -> "#6C5CE7"
            State.ANGRY -> "#FF4444"
            State.THINKING -> "#FFB800"
            else -> "#00FFD1"
        }
        glowPaint.color = Color.parseColor(hexColor)
    }

    private fun startAnimationLoop() {
        postDelayed(object : Runnable {
            override fun run() {
                animAngle += 0.15f
                // Random blink every 4-6 seconds
                if (Math.random() < 0.02) {
                    isBlinking = true
                    postDelayed({ isBlinking = false }, 150)
                }
                invalidate()
                postDelayed(this, 33) // ~30 fps
            }
        }, 33)
    }

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.action) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                val cx = width / 2f
                val cy = height / 2f
                pupilX = ((event.x - cx) / cx).coerceIn(-1f, 1f) * 40f
                pupilY = ((event.y - cy) / cy).coerceIn(-1f, 1f) * 40f
                invalidate()
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                pupilX = 0f
                pupilY = 0f
                invalidate()
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.BLACK) // Pure AMOLED Black

        val w = width.toFloat()
        val h = height.toFloat()
        if (w == 0f || h == 0f) return

        val unit = min(w, h)
        val cellSize = max(6f, unit / 48f)
        val cx = w / 2f
        val cy = h / 2f - 40f
        val eyeR = unit / 7f
        val gap = eyeR * 1.4f

        val leftEyeX = cx - gap + pupilX
        val rightEyeX = cx + gap + pupilX
        val eyeY = cy + pupilY

        // Draw Soft Ambient Glow behind eyes
        canvas.drawCircle(leftEyeX, eyeY, eyeR * 1.4f, glowPaint.apply { alpha = 40 })
        canvas.drawCircle(rightEyeX, eyeY, eyeR * 1.4f, glowPaint.apply { alpha = 40 })

        if (isBlinking) {
            // Draw Blinking Lines
            drawRectGrid(canvas, leftEyeX - eyeR, eyeY - 4f, eyeR * 2f, 8f, cellSize)
            drawRectGrid(canvas, rightEyeX - eyeR, eyeY - 4f, eyeR * 2f, 8f, cellSize)
            return
        }

        // Draw Eyes according to state
        when (currentState) {
            State.HAPPY, State.EXCITED -> {
                // Smiling arch eyes
                drawArchEye(canvas, leftEyeX, eyeY, eyeR, cellSize)
                drawArchEye(canvas, rightEyeX, eyeY, eyeR, cellSize)
            }
            State.ANGRY -> {
                // Slanted angry eyes
                drawCircleGrid(canvas, leftEyeX, eyeY, eyeR, cellSize)
                drawCircleGrid(canvas, rightEyeX, eyeY, eyeR, cellSize)
                // Draw slant mask
                drawSlantEyebrow(canvas, leftEyeX, eyeY, eyeR, isLeft = true, cellSize)
                drawSlantEyebrow(canvas, rightEyeX, eyeY, eyeR, isLeft = false, cellSize)
            }
            State.CONFUSED, State.CURIOUS -> {
                // Asymmetric eyes
                drawCircleGrid(canvas, leftEyeX, eyeY - 10f, eyeR * 1.15f, cellSize)
                drawCircleGrid(canvas, rightEyeX, eyeY + 10f, eyeR * 0.85f, cellSize)
            }
            State.THINKING -> {
                // Calculation loop
                drawCircleGrid(canvas, leftEyeX, eyeY, eyeR, cellSize)
                drawCircleGrid(canvas, rightEyeX, eyeY, eyeR, cellSize)
                val ox = cos(animAngle) * 20f
                val oy = sin(animAngle) * 20f
                drawRectGrid(canvas, cx + ox - 10f, cy + eyeR + 30f + oy, 20f, 20f, cellSize)
            }
            else -> {
                // Default round LED eyes
                drawCircleGrid(canvas, leftEyeX, eyeY, eyeR, cellSize)
                drawCircleGrid(canvas, rightEyeX, eyeY, eyeR, cellSize)
            }
        }

        // Draw Mouth
        val mouthY = cy + eyeR + 50f
        if (currentState == State.SPEAKING || currentState == State.HAPPY || currentState == State.EXCITED) {
            // Bouncing smile mouth
            val mouthW = gap * 0.8f
            val mouthH = 14f + (sin(animAngle * 2) * 6f)
            drawArchMouth(canvas, cx, mouthY, mouthW, mouthH, cellSize)
        } else {
            // Resting flat mouth
            drawRectGrid(canvas, cx - 25f, mouthY, 50f, 10f, cellSize)
        }
    }

    private fun drawCircleGrid(canvas: Canvas, cx: Float, cy: Float, r: Float, cellSize: Float) {
        val r2 = r * r
        var y = -r
        while (y <= r) {
            var x = -r
            while (x <= r) {
                if (x * x + y * y <= r2) {
                    canvas.drawRect(
                        cx + x, cy + y,
                        cx + x + cellSize - 1f, cy + y + cellSize - 1f,
                        ledPaint
                    )
                }
                x += cellSize
            }
            y += cellSize
        }
    }

    private fun drawRectGrid(canvas: Canvas, x: Float, y: Float, w: Float, h: Float, cellSize: Float) {
        var cy = y
        while (cy < y + h) {
            var cx = x
            while (cx < x + w) {
                canvas.drawRect(
                    cx, cy,
                    cx + cellSize - 1f, cy + cellSize - 1f,
                    ledPaint
                )
                cx += cellSize
            }
            cy += cellSize
        }
    }

    private fun drawArchEye(canvas: Canvas, cx: Float, cy: Float, r: Float, cellSize: Float) {
        var x = -r
        while (x <= r) {
            val y = -kotlin.math.sqrt(max(0f, r * r - x * x)) * 0.6f
            canvas.drawRect(cx + x, cy + y, cx + x + cellSize, cy + y + cellSize * 2f, ledPaint)
            x += cellSize
        }
    }

    private fun drawSlantEyebrow(canvas: Canvas, cx: Float, cy: Float, r: Float, isLeft: Boolean, cellSize: Float) {
        val paint = Paint().apply { color = Color.BLACK }
        val path = android.graphics.Path()
        if (isLeft) {
            path.moveTo(cx - r, cy - r)
            path.lineTo(cx + r, cy - r + 20f)
            path.lineTo(cx - r, cy - r + 20f)
        } else {
            path.moveTo(cx + r, cy - r)
            path.lineTo(cx - r, cy - r + 20f)
            path.lineTo(cx + r, cy - r + 20f)
        }
        path.close()
        canvas.drawPath(path, paint)
    }

    private fun drawArchMouth(canvas: Canvas, cx: Float, cy: Float, w: Float, h: Float, cellSize: Float) {
        var x = -w
        while (x <= w) {
            val y = (x * x) / (w * 1.5f)
            canvas.drawRect(cx + x, cy + y, cx + x + cellSize, cy + y + cellSize * 1.5f, ledPaint)
            x += cellSize
        }
    }
}
