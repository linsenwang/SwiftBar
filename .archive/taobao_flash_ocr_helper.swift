#!/usr/bin/env swift
import Cocoa
import Vision
import Foundation

let args = CommandLine.arguments
if args.count < 2 {
    print("Usage: taobao_flash_ocr_helper <image.png>")
    exit(1)
}

let imagePath = args[1]
let imageURL = URL(fileURLWithPath: imagePath)

guard let image = NSImage(contentsOf: imageURL) else {
    print("无法加载图片: \(imagePath)", to: &stderr)
    exit(1)
}

var cgImage: CGImage?
if let tiffData = image.tiffRepresentation,
   let bitmap = NSBitmapImageRep(data: tiffData) {
    cgImage = bitmap.cgImage
}

guard let cgImage = cgImage else {
    print("无法转换为 CGImage", to: &stderr)
    exit(1)
}

let semaphore = DispatchSemaphore(value: 0)
var resultLines: [String] = []
var resultError: String?

let request = VNRecognizeTextRequest { request, error in
    defer { semaphore.signal() }
    if let error = error {
        resultError = error.localizedDescription
        return
    }
    guard let observations = request.results as? [VNRecognizedTextObservation] else {
        return
    }
    for observation in observations {
        guard let candidate = observation.topCandidates(1).first else { continue }
        resultLines.append(candidate.string)
    }
}

// 优先简体中文，其次英文
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    print("OCR 执行失败: \(error.localizedDescription)", to: &stderr)
    exit(1)
}

semaphore.wait(timeout: .now() + 30)

if let resultError = resultError {
    print("OCR 失败: \(resultError)", to: &stderr)
    exit(1)
}

for line in resultLines {
    print(line)
}

extension FileHandle: TextOutputStream {
    public func write(_ string: String) {
        guard let data = string.data(using: .utf8) else { return }
        self.write(data)
    }
}

var stderr = FileHandle.standardError
