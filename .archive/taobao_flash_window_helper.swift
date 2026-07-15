#!/usr/bin/env swift
import Cocoa
import CoreGraphics
import Foundation

struct WindowInfo: Codable {
    let id: Int
    let owner: String
    let name: String
    let x: CGFloat
    let y: CGFloat
    let width: CGFloat
    let height: CGFloat
}

func listWindows() -> [WindowInfo] {
    guard let windowList = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] else {
        return []
    }

    var result: [WindowInfo] = []
    for info in windowList {
        let windowID = info[kCGWindowNumber as String] as? Int ?? -1
        let ownerName = info[kCGWindowOwnerName as String] as? String ?? ""
        let name = info[kCGWindowName as String] as? String ?? ""
        let boundsDict = info[kCGWindowBounds as String] as? [String: CGFloat] ?? [:]

        let bounds = CGRect(
            x: boundsDict["X"] ?? 0,
            y: boundsDict["Y"] ?? 0,
            width: boundsDict["Width"] ?? 0,
            height: boundsDict["Height"] ?? 0
        )

        result.append(WindowInfo(
            id: windowID,
            owner: ownerName,
            name: name,
            x: bounds.origin.x,
            y: bounds.origin.y,
            width: bounds.size.width,
            height: bounds.size.height
        ))
    }
    return result
}

func findWindow(keyword: String, owner: String?) -> WindowInfo? {
    let windows = listWindows()
    return windows.first { w in
        let ownerMatch = owner == nil || w.owner == owner!
        return ownerMatch && (w.name.contains(keyword) || w.owner.contains(keyword))
    }
}

let args = CommandLine.arguments
if args.count > 1 && args[1] == "--find" {
    let keyword = args.count > 2 ? args[2] : "淘宝闪购"
    let owner = args.count > 3 ? args[3] : nil
    if let w = findWindow(keyword: keyword, owner: owner) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        if let data = try? encoder.encode(w) {
            print(String(data: data, encoding: .utf8) ?? "")
        }
    } else {
        print("null")
        exit(1)
    }
} else {
    let encoder = JSONEncoder()
    encoder.outputFormatting = .prettyPrinted
    let data = try! encoder.encode(listWindows())
    print(String(data: data, encoding: .utf8) ?? "")
}
