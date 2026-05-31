import AppKit
import Foundation
import MediaPlayer

private struct InputMessage: Decodable {
    let type: String
    let title: String?
    let artist: String?
    let album: String?
    let duration: Double?
    let position: Double?
    let state: Int?
    let active: Bool?
}

private final class NowPlayingBridge {
    private let baseURL: URL
    private let commandCenter = MPRemoteCommandCenter.shared()
    private let nowPlayingCenter = MPNowPlayingInfoCenter.default()
    private let commandQueue = DispatchQueue(label: "com.mindinguflac.nowplaying.command")

    private var title = ""
    private var artist = ""
    private var album = ""
    private var duration: Double = 1
    private var position: Double = 0
    private var playbackState = 0
    private var appActive = false

    init(baseURL: URL) {
        self.baseURL = baseURL
        installRemoteCommands()
    }

    func handle(_ message: InputMessage) {
        switch message.type {
        case "set_now_playing":
            if let title = message.title { self.title = title }
            if let artist = message.artist { self.artist = artist }
            if let album = message.album { self.album = album }
            if let duration = message.duration, duration > 0 { self.duration = duration }
            if let position = message.position, position >= 0 { self.position = position }
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
        guard playbackState == 1 || playbackState == 2, !title.isEmpty else {
            DispatchQueue.main.async { self.clearPublishedNowPlaying() }
            return
        }

        let isPlaying = playbackState == 1
        let info: [String: Any] = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: artist,
            MPMediaItemPropertyAlbumTitle: album,
            MPMediaItemPropertyPlaybackDuration: max(duration, 1),
            MPNowPlayingInfoPropertyElapsedPlaybackTime: max(position, 0),
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0,
            MPNowPlayingInfoPropertyCurrentPlaybackDate: Date(),
        ]
        let npState: MPNowPlayingPlaybackState = isPlaying ? .playing : .paused
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.nowPlayingCenter.nowPlayingInfo = info
            self.nowPlayingCenter.playbackState = npState
            self.updateCommandAvailability(true)
        }
    }

    private func clearPublishedNowPlaying() {
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
