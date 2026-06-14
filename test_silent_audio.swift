import AVFoundation

let engine = AVAudioEngine()
let player = AVAudioPlayerNode()
engine.attach(player)

let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!
engine.connect(player, to: engine.mainMixerNode, format: format)

try! engine.start()
player.play()

print("Started silent audio")
RunLoop.main.run(until: Date(timeIntervalSinceNow: 2))
