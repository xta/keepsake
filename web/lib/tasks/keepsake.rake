namespace :keepsake do
  desc "Mint an invitation link. EMAIL is optional and advisory. HOST sets the link's origin."
  task invite: :environment do
    # APP_HOST is set per deployment; HOST overrides it for one-off use. A
    # localhost default is right in development and useless in production,
    # which is exactly where an invite link gets emailed to somebody.
    host =
      if ENV["HOST"].present?
        ENV["HOST"]
      elsif ENV["APP_HOST"].present?
        ENV["APP_HOST"].start_with?("http") ? ENV["APP_HOST"] : "https://#{ENV['APP_HOST']}"
      else
        "http://localhost:3000"
      end

    # The first invite on a fresh install has no creator, because there is
    # nobody yet. After that, attribute it to the first user unless told
    # otherwise -- an invite-only app is only as accountable as its trail.
    creator =
      if ENV["FROM"].present?
        User.find_by!(email_address: ENV["FROM"].downcase)
      else
        User.order(:id).first
      end

    invite = Invite.create!(created_by: creator, email_address: ENV["EMAIL"].presence)

    puts
    puts "  #{host}/invites/#{invite.token}"
    puts
    puts "  expires #{invite.expires_at.to_fs(:long)}"
    puts "  #{creator ? "from #{creator.email_address}" : 'first invite on this install (no creator)'}"
    puts
  end

  desc "List invitations and whether they have been used."
  task invites: :environment do
    if Invite.none?
      puts "No invitations yet. Run: bin/rails keepsake:invite"
      next
    end

    Invite.order(created_at: :desc).each do |invite|
      state =
        if invite.claimed? then "claimed by #{invite.claimed_by&.email_address}"
        elsif invite.expired? then "expired"
        else "open until #{invite.expires_at.to_fs(:short)}"
        end
      puts format("  %-34s %s", invite.token, state)
    end
  end

  desc "Re-save every library so pasted values are re-normalised (region, bucket, endpoint, keys)."
  task renormalize: :environment do
    changed = 0

    Library.find_each do |library|
      before = library.slice(:region, :bucket, :endpoint, :label, :access_key_id)
      library.valid? # runs the before_validation sanitizers
      after = library.slice(:region, :bucket, :endpoint, :label, :access_key_id)

      next if before == after

      diff = after.reject { |k, v| before[k] == v }
      if library.save
        changed += 1
        puts "  #{library.label}"
        diff.each { |field, value| puts "    #{field}: #{before[field].inspect} -> #{value.inspect}" }
      else
        puts "  #{library.label}: could not save -- #{library.errors.full_messages.to_sentence}"
      end
    end

    puts changed.zero? ? "Nothing needed changing." : "Updated #{changed}."
  end

  desc "Development only: create a demo account with the fixture library attached."
  task demo: :environment do
    abort "Refusing to run outside development or test." unless Rails.env.local?

    email = ENV.fetch("EMAIL", "demo@example.com").downcase
    password = ENV.fetch("PASSWORD", SecureRandom.alphanumeric(16))

    user = User.find_by(email_address: email)
    if user
      puts "#{email} already exists; leaving its password alone."
    else
      user = User.create!(email_address: email, password: password)
      puts "Created #{email}"
      puts "  password: #{password}"
    end

    Rake::Task["keepsake:demo_library"].invoke
  end

  desc "Development only: remove accounts created by keepsake:demo, and their libraries."
  task undemo: :environment do
    abort "Refusing to run outside development or test." unless Rails.env.local?

    scope = User.where("email_address LIKE ?", "%@example.com")
    if scope.none?
      puts "Nothing to remove."
      next
    end

    scope.each { |u| puts "  removing #{u.email_address} (#{u.libraries.count} libraries)" }
    scope.destroy_all
    puts "Done. Nothing in any bucket was touched."
  end

  desc "Development only: attach the bundled fixture library to a user. EMAIL selects the user."
  task demo_library: :environment do
    abort "Refusing to run outside development or test." unless Rails.env.local?

    user =
      if ENV["EMAIL"].present?
        User.find_by!(email_address: ENV["EMAIL"].downcase)
      else
        User.order(:id).first
      end
    abort "No users yet. Run bin/rails keepsake:demo, or claim an invite: bin/rails keepsake:invite" unless user

    path = Rails.root.join("test/fixtures/library").to_s
    library = user.libraries.find_or_initialize_by(label: "Fixture library")
    library.assign_attributes(
      provider: "local", bucket: path,
      access_key_id: "not-used", secret_access_key: "not-used",
      access_level: "read_only"
    )
    library.save!

    puts "Attached #{path}"
    puts "  to #{user.email_address} as \"#{library.label}\""
    puts "  http://localhost:3000/libraries/#{library.id}"
  end
end
