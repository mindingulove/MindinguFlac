import Foundation

let handle = dlopen("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote", RTLD_NOW)
if handle != nil {
    let sym = dlsym(handle, "MRMediaRemoteSetCanBeNowPlayingApplication")
    if sym != nil {
        typealias Fn = @convention(c) (Bool) -> Void
        let fn = unsafeBitCast(sym, to: Fn.self)
        fn(true)
        print("Success")
    } else {
        print("Symbol not found")
    }
} else {
    print("Framework not found")
}
