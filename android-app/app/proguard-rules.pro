# Everything the embedded Python backend reaches is reached *reflectively*,
# through Chaquopy's `java.jclass("...")`. R8 sees no call site for any of it,
# so without these rules a minified release build strips or renames the exact
# classes the backend needs and the engine fails on the phone instead of in CI.
-keep class com.chaquo.python.** { *; }
-keep class com.mindinguflac.android.MainActivity$AndroidBridge { *; }

# AndroidTorrentEngine (jlibtorrent bridge), NanoAdvisor and LocalGemmaAdvisor
# are only ever named as strings from Python.
-keep class com.mindinguflac.android.** { *; }
# jlibtorrent's SWIG layer registers its natives by fully-qualified name, so
# renaming any of it breaks the JNI lookup against libjlibtorrent.so.
-keep class com.frostwire.jlibtorrent.** { *; }
-keepclasseswithmembernames class * {
    native <methods>;
}

# MediaPipe's tasks-genai pulls in AutoValue's shaded JavaPoet, which
# references javax.lang.model — a compile-time-only API that does not exist on
# Android. None of it is reachable at runtime; R8 only needs to be told not to
# treat the dangling references as an error.
-dontwarn javax.lang.model.**
-dontwarn autovalue.shaded.**
