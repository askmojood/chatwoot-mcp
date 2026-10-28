# Run once inside the Chatwoot container (scripts/up.sh): make the demo account and its admin (shown as "Claude
# Connector" on every change it makes) with the generated password, and print the admin's API access token.
account = Account.find_by(name: 'Harbor Trading (SAMPLE)') || Account.create!(name: 'Harbor Trading (SAMPLE)')
email = 'admin@harbor-trading.example'
user = User.find_by(email: email) || User.create!(name: 'Claude Connector', email: email,
                                                  password: ENV.fetch('ADMIN_PASSWORD'), confirmed_at: Time.current)
AccountUser.find_or_create_by!(account: account, user: user) { |au| au.role = :administrator }
# The installation is set up: skip Chatwoot's first-run onboarding page.
::Redis::Alfred.delete(::Redis::Alfred::CHATWOOT_INSTALLATION_ONBOARDING)
puts "ACCOUNT=#{account.id}"
puts "TOKEN=#{user.access_token.token}"
