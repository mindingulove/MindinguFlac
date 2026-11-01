import org.gradle.api.tasks.Sync

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

val repositoryRoot = rootProject.projectDir.parentFile
val generatedPython = layout.buildDirectory.dir("generated/python/main")
val generatedJniLibs = layout.buildDirectory.dir("generated/jniLibs")
val jlibtorrentNativeJar = projectDir.resolve("libs/jlibtorrent-android-arm64-2.0.12.9.jar")
val localWheelDir = providers.environmentVariable("MINDINGUFLAC_ANDROID_WHEELS").orNull
val bundledWheelDir = projectDir.resolve("python-wheels")

val prepareLyricsAlignment by tasks.registering(Exec::class) {
    workingDir(repositoryRoot)
    commandLine(providers.environmentVariable("MINDINGUFLAC_BUILD_PYTHON").orElse("python3.12").get(),
        "scripts/prepare_lyrics_alignment.py")
}

val syncPythonSources by tasks.registering(Sync::class) {
    dependsOn(prepareLyricsAlignment)
    includeEmptyDirs = false
    from(repositoryRoot) {
        include("*.py", "local_metadata/**")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    from(repositoryRoot.resolve("vendor/mornye-python")) {
        include("mornye/**")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    from("src/main/python") {
        exclude("android_runtime/static/**")
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    from(repositoryRoot.resolve("vendor/mornye-extensions")) {
        exclude(".DS_Store", "**/.DS_Store", "README.md")
        into("android_runtime/mornye_extensions")
    }
    from(repositoryRoot.resolve("static")) {
        exclude(".DS_Store", "**/.DS_Store")
        into("android_runtime/static")
    }
    from(repositoryRoot.resolve("assets/lyrics-alignment")) {
        include("*.bin", "LICENSE*")
        into("android_runtime/lyrics_models")
    }
    from(repositoryRoot.resolve("native/lyrics_alignment")) {
        include("assets.json", "THIRD_PARTY_NOTICES.md")
        into("android_runtime/lyrics_models")
    }
    into(generatedPython)
}

// jlibtorrent's loader tries a classpath resource first, and on Android the
// APK *is* the classpath root — so a .so packaged as
// `lib/arm64-v8a/libjlibtorrent-<version>.so` gets found as a resource,
// re-extracted into the app's writable cache on every cold start, and loaded
// from there. Android 16 already warns that loading a writable file "will
// throw on a future Android version". Repacking it under the plain
// `libjlibtorrent.so` name makes the resource lookup miss and
// `System.loadLibrary("jlibtorrent")` resolve it read-only from inside the
// APK, which is the supported path.
val extractJlibtorrentNative by tasks.registering(Copy::class) {
    from(zipTree(jlibtorrentNativeJar)) {
        include("lib/arm64-v8a/*.so")
        eachFile { path = "arm64-v8a/libjlibtorrent.so" }
    }
    includeEmptyDirs = false
    into(generatedJniLibs)
}

// Mornye's JavaScript providers run under Node. Android only executes files
// from the app's native library directory, so the pinned standalone Node is
// packaged as a lib*.so and extracted at install (useLegacyPackaging below).
val prepareAndroidNode by tasks.registering(Exec::class) {
    val output = generatedJniLibs.get().file("arm64-v8a/libmindinguflac_node.so").asFile
    workingDir(repositoryRoot)
    commandLine(providers.environmentVariable("MINDINGUFLAC_BUILD_PYTHON").orElse("python3.12").get(),
        "scripts/prepare_android_node.py", output.absolutePath)
    inputs.file(repositoryRoot.resolve("scripts/prepare_android_node.py"))
    outputs.file(output)
}

// ffmpeg/ffprobe for Mornye's providers, cross-compiled from pinned FFmpeg
// source with this project's NDK and packaged like Node above.
val buildAndroidFfmpeg by tasks.registering(Exec::class) {
    val folder = generatedJniLibs.get().dir("arm64-v8a").asFile
    workingDir(repositoryRoot)
    inputs.file(repositoryRoot.resolve("scripts/build_android_ffmpeg.py"))
    outputs.files(folder.resolve("libmindinguflac_ffmpeg.so"), folder.resolve("libmindinguflac_ffprobe.so"))
    doFirst {
        commandLine(providers.environmentVariable("MINDINGUFLAC_BUILD_PYTHON").orElse("python3.12").get(),
            "scripts/build_android_ffmpeg.py", "--ndk", android.ndkDirectory.absolutePath,
            folder.resolve("libmindinguflac_ffmpeg.so").absolutePath,
            folder.resolve("libmindinguflac_ffprobe.so").absolutePath)
    }
}

android {
    namespace = "com.mindinguflac.android"
    compileSdk = 35
    ndkVersion = "27.3.13750724"

    defaultConfig {
        applicationId = "com.mindinguflac.android"
        minSdk = 26
        targetSdk = 35
        versionCode = 36
        versionName = "1.4"

        externalNativeBuild {
            cmake { arguments += listOf("-DANDROID_STL=c++_static") }
        }
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    externalNativeBuild {
        cmake {
            path = repositoryRoot.resolve("native/lyrics_alignment/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        getByName("main") {
            jniLibs.srcDir(generatedJniLibs)
        }
    }

    packaging {
        jniLibs {
            // Extract native libraries to nativeLibraryDir: Node must exist
            // there as a real file to be executed.
            useLegacyPackaging = true
            // Already stripped; leave the executable exactly as verified.
            keepDebugSymbols += listOf("**/libmindinguflac_node.so", "**/libmindinguflac_ffmpeg.so",
                "**/libmindinguflac_ffprobe.so")
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython(providers.environmentVariable("MINDINGUFLAC_BUILD_PYTHON").orElse("python3.12").get())
        pip {
            options("--no-index", "--find-links", bundledWheelDir.absolutePath)
            if (!localWheelDir.isNullOrBlank()) options("--find-links", localWheelDir)
            install("-r", "src/main/python/android-requirements.txt")
        }
        pyc {
            src = false
        }
        extractPackages("android_runtime")
    }
    sourceSets {
        getByName("main") {
            setSrcDirs(listOf(generatedPython))
        }
    }
}

tasks.named("preBuild").configure {
    dependsOn(syncPythonSources, extractJlibtorrentNative, prepareAndroidNode, buildAndroidFfmpeg)
}

tasks.configureEach {
    if (name.startsWith("configureCMake") || name.startsWith("buildCMake")) {
        dependsOn(prepareLyricsAlignment)
    }
    if (name.startsWith("merge") && name.endsWith("PythonSources")) {
        dependsOn(syncPythonSources)
    }
    if (name.startsWith("merge") && name.endsWith("JniLibFolders")) {
        dependsOn(extractJlibtorrentNative, prepareAndroidNode, buildAndroidFfmpeg)
    }
}

dependencies {
    implementation("androidx.core:core:1.13.1")
    // Custom Tabs for the Mornye provider check (MornyeVerification), as in Mornye's app.
    implementation("androidx.browser:browser:1.8.0")
    // jlibtorrent is the real native torrent engine used by the Android FLAC
    // backend. Only the Java/SWIG bindings go on the classpath; the arm64 JNI
    // library is repacked into jniLibs by extractJlibtorrentNative above, so
    // it is loaded from the APK rather than extracted to writable storage.
    implementation(files("libs/jlibtorrent-2.0.12.9.jar"))
    implementation("com.google.mlkit:genai-prompt:1.0.0-beta4")
    implementation("com.google.mediapipe:tasks-genai:0.10.21")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    // Native playback on a chosen output device (NativeAudioPlayer). The
    // OkHttp data source gives HTTP/2, which Monochrome's storage requires.
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-datasource-okhttp:1.4.1")
}
