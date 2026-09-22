"""Compile the actual modifier against old/new SDK-shaped modules."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / 'Sources/AIUsageMenuBarApp/MenuBarPopoverView.swift'
MODULE = '''
public protocol View {}
public protocol ViewModifier { typealias Content = FixtureContent }
public enum Choice<A: View, B: View>: View { case a(A), b(B) }
@resultBuilder public struct ViewBuilder {
 public static func buildBlock<T: View>(_ value: T) -> T { value }
 public static func buildEither<A: View,B: View>(first: A) -> Choice<A,B> { .a(first) }
 public static func buildEither<A: View,B: View>(second: B) -> Choice<A,B> { .b(second) }
 public static func buildLimitedAvailability<T: View>(_ value: T) -> T { value }
}
public enum NSColor { case windowBackgroundColor }
public struct Color: View { public init(nsColor: NSColor) {} }
public enum RoundedCornerStyle { case continuous }
public struct RoundedRectangle { public init(cornerRadius: Double, style: RoundedCornerStyle) {} }
public enum Glass { case regular }
public struct FixtureContent: View {
 public init() {}
 public func background<T: View>(_ value: T) -> FixtureContent { self }
 GLASS_API
}
'''


@unittest.skipUnless(shutil.which('xcrun'), 'requires the Mac Swift compiler')
class GlassSDKCompatibilityTests(unittest.TestCase):
    def test_real_modifier_builds_with_old_sdk_and_uses_glass_with_new_sdk(self):
        source = SOURCE.read_text()
        modifier = source.split('private struct PopoverGlassSurface:', 1)[1].split('private struct MacOSGlassBackground:', 1)[0]
        modifier = 'private struct PopoverGlassSurface:' + modifier
        modifier = modifier.replace('canImport(SwiftUI,', 'canImport(FixtureSwiftUI,')
        with tempfile.TemporaryDirectory(prefix='glass-sdk-') as directory:
            root = Path(directory)
            checked = 0
            for version in (6, 7):
                with self.subTest(sdk=version):
                    target = root / str(version)
                    target.mkdir()
                    api = 'public func glassEffect(_ glass: Glass, in shape: RoundedRectangle) -> FixtureContent { self }' if version == 7 else ''
                    module = target / 'Fixture.swift'
                    module.write_text(MODULE.replace('GLASS_API', api))
                    built = subprocess.run(['xcrun', 'swiftc', '-emit-module', '-module-name', 'FixtureSwiftUI',
                                    '-user-module-version', str(version), str(module),
                                    '-module-cache-path', str(target / 'cache'),
                                    '-emit-module-path', str(target / 'FixtureSwiftUI.swiftmodule')],
                                   capture_output=True, text=True)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    probe = target / 'Probe.swift'
                    probe.write_text('import FixtureSwiftUI\nstruct MacOSGlassBackground: View {}\n' + modifier)
                    result = subprocess.run(['xcrun', 'swiftc', '-typecheck', '-dump-ast', '-module-cache-path', str(target / 'cache'), '-I', str(target), str(probe)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual('FixtureContent.glassEffect' in result.stdout, version == 7)
                    checked += 1
            self.assertEqual(checked, 2)
