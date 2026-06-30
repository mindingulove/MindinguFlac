import AppKit
import Foundation
import MediaPlayer
import AVFoundation

private struct InputMessage: Decodable {
    let type: String
    let title: String?
    let artist: String?
    let album: String?
    let duration: Double?
    let position: Double?
    let state: Int?
    let active: Bool?
    let artwork_url: String?
}

private final class NowPlayingBridge {
    private let baseURL: URL
    private let commandCenter = MPRemoteCommandCenter.shared()
    private let nowPlayingCenter = MPNowPlayingInfoCenter.default()
    private let commandQueue = DispatchQueue(label: "com.mindinguflac.nowplaying.command")

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()

    private var title = ""
    private var artist = ""
    private var album = ""
    private var duration: Double = 1
    private var position: Double = 0
    private var playbackState = 0
    private var appActive = false
    private var artworkURL = ""
    private var artworkImage: NSImage? = nil
    private var activity: NSObjectProtocol?

    init(baseURL: URL) {
        self.baseURL = baseURL
        installRemoteCommands()
        
        // Force macOS to recognize this background app as a Now Playing app
        if let handle = dlopen("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote", RTLD_NOW) {
            if let sym = dlsym(handle, "MRMediaRemoteSetCanBeNowPlayingApplication") {
                typealias Fn = @convention(c) (Bool) -> Void
                let fn = unsafeBitCast(sym, to: Fn.self)
                fn(true)
            }
        }

        engine.attach(player)
        if let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2) {
            engine.connect(player, to: engine.mainMixerNode, format: format)
            try? engine.start()
            
            if let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 44100) {
                buffer.frameLength = 44100
                // Add a virtually imperceptible value to prevent silence optimization
                if let floatChannelData = buffer.floatChannelData {
                    for channel in 0..<Int(format.channelCount) {
                        for frame in 0..<Int(buffer.frameLength) {
                            floatChannelData[channel][frame] = Float.ulpOfOne
                        }
                    }
                }
                player.scheduleBuffer(buffer, at: nil, options: .loops, completionHandler: nil)
            }
        }
    }

    func handle(_ message: InputMessage) {
        switch message.type {
        case "set_now_playing":
            if let title = message.title { self.title = title }
            if let artist = message.artist { self.artist = artist }
            if let album = message.album { self.album = album }
            if let duration = message.duration, duration > 0 { self.duration = duration }
            if let position = message.position, position >= 0 { self.position = position }
            
            if let newArt = message.artwork_url, newArt != self.artworkURL {
                self.artworkURL = newArt
                self.artworkImage = nil
                
                let artURL: URL?
                if newArt.hasPrefix("http") {
                    artURL = URL(string: newArt)
                } else {
                    artURL = URL(string: newArt, relativeTo: baseURL)
                }

                if let parsed = artURL {
                    URLSession.shared.dataTask(with: parsed) { [weak self] data, _, _ in
                        guard let self = self, let data = data, let image = NSImage(data: data) else { return }
                        DispatchQueue.main.async {
                            if self.artworkURL == newArt {
                                self.artworkImage = image
                                self.refresh()
                            }
                        }
                    }.resume()
                }
            }
            refresh()
        case "set_playback_state":
            playbackState = message.state ?? 0
            refresh()
        case "clear_now_playing":
            resetAndClear()
        case "app_active":
            appActive = message.active ?? false
            refresh()
        default:
            break
        }
    }

    private func installRemoteCommands() {
        let handlers: [(MPRemoteCommand, String)] = [
            (commandCenter.playCommand, "playPause"),
            (commandCenter.pauseCommand, "playPause"),
            (commandCenter.togglePlayPauseCommand, "playPause"),
            (commandCenter.nextTrackCommand, "btnNext"),
            (commandCenter.previousTrackCommand, "btnPrev"),
        ]

        for (command, action) in handlers {
            command.addTarget { [weak self] _ in
                self?.sendAction(action)
                return .success
            }
        }
        updateCommandAvailability(false)
    }

    private func refresh() {
        guard !title.isEmpty else {
            return
        }

        guard playbackState == 1 || playbackState == 2 else {
            DispatchQueue.main.async { self.clearPublishedNowPlaying() }
            return
        }

        let isPlaying = playbackState == 1
        
        if isPlaying {
            player.play()
            if activity == nil {
                activity = ProcessInfo.processInfo.beginActivity(options: [.userInitiatedAllowingIdleSystemSleep], reason: "Now Playing Activity")
            }
        } else {
            player.pause()
            if let act = activity {
                ProcessInfo.processInfo.endActivity(act)
                activity = nil
            }
        }

        var info: [String: Any] = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: artist,
            MPMediaItemPropertyAlbumTitle: album,
            MPMediaItemPropertyPlaybackDuration: max(duration, 1),
            MPNowPlayingInfoPropertyElapsedPlaybackTime: max(position, 0),
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0,
            MPNowPlayingInfoPropertyCurrentPlaybackDate: Date(),
        ]
        
        if let image = artworkImage {
            info[MPMediaItemPropertyArtwork] = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
        }
        
        let npState: MPNowPlayingPlaybackState = isPlaying ? .playing : .paused
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.nowPlayingCenter.nowPlayingInfo = info
            self.nowPlayingCenter.playbackState = npState
            self.updateCommandAvailability(true)
        }
    }

    private func clearPublishedNowPlaying() {
        player.pause()
        nowPlayingCenter.nowPlayingInfo = nil
        nowPlayingCenter.playbackState = .stopped
        updateCommandAvailability(false)
    }

    private func resetAndClear() {
        title = ""
        artist = ""
        album = ""
        duration = 1
        position = 0
        playbackState = 0
        artworkURL = ""
        artworkImage = nil
        
        if let act = activity {
            ProcessInfo.processInfo.endActivity(act)
            activity = nil
        }
        
        clearPublishedNowPlaying()
    }

    private func updateCommandAvailability(_ enabled: Bool) {
        commandCenter.togglePlayPauseCommand.isEnabled = enabled
        commandCenter.playCommand.isEnabled = enabled
        commandCenter.pauseCommand.isEnabled = enabled
        commandCenter.nextTrackCommand.isEnabled = enabled
        commandCenter.previousTrackCommand.isEnabled = enabled
    }

    private func sendAction(_ action: String) {
        commandQueue.async { [baseURL] in
            guard let url = URL(string: "api/macos_media_command", relativeTo: baseURL) else { return }
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": action])
            URLSession.shared.dataTask(with: request).resume()
        }
    }
}

private func readBaseURL() -> URL? {
    let args = CommandLine.arguments
    guard let index = args.firstIndex(of: "--base-url"), index + 1 < args.count else { return nil }
    return URL(string: args[index + 1])
}

@main
struct MindinguflacNowPlayingMain {
    static func main() {
        guard let baseURL = readBaseURL() else {
            fputs("missing --base-url\n", stderr)
            exit(2)
        }

        let bridge = NowPlayingBridge(baseURL: baseURL)
        DispatchQueue.global(qos: .background).async {
            while let line = readLine(strippingNewline: true) {
                guard let data = line.data(using: .utf8),
                      let message = try? JSONDecoder().decode(InputMessage.self, from: data) else {
                    continue
                }
                bridge.handle(message)
            }
            exit(0)
        }

        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        app.run()
    }
}
