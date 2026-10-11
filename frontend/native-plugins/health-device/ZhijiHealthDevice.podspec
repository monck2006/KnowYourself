Pod::Spec.new do |s|
  s.name = 'ZhijiHealthDevice'
  s.version = '0.1.0'
  s.summary = 'Read-only HealthKit bridge for Zhiji'
  s.license = { :type => 'MIT' }
  s.homepage = 'https://capacitorjs.com'
  s.author = 'Zhiji'
  # Local-only plugin. This app resolves Package.swift through Capacitor SPM;
  # no remote CocoaPods distribution is configured.
  s.source_files = 'ios/Sources/**/*.{swift,h,m}'
  s.ios.deployment_target = '15.0'
  s.dependency 'Capacitor', '>= 8.0.0'
  s.swift_version = '5.9'
  s.frameworks = 'HealthKit'
end
