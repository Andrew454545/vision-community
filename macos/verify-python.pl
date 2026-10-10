# Check the complete private interpreter before executing any of its code.
# Uses only modules included with the system Perl on macOS.
use strict;
use warnings;
use Digest::SHA qw(sha256_hex);
use JSON::PP qw(decode_json);
use File::Find;
use File::Basename qw(dirname);
use Fcntl qw(:mode);

sub mismatch { die "private_python_mismatch\n"; }
my ($manifest, $expected, $root) = @ARGV;
@ARGV == 3 && $expected =~ /\A[a-f0-9]{64}\z/ && -d $root && !-l $root or mismatch();
open my $metadata, '<:raw', $manifest or mismatch();
my $raw; { local $/; $raw = <$metadata>; }
close $metadata;
length($raw) <= 2 * 1024 * 1024 && sha256_hex($raw) eq $expected or mismatch();
my $pins = eval { decode_json($raw) }; $pins && ref($pins) eq 'HASH' or mismatch();
$pins->{version} == 1 && ref($pins->{files}) eq 'HASH' && ref($pins->{links}) eq 'HASH'
    && ref($pins->{directories}) eq 'ARRAY' or mismatch();
my %dirs = map { $_ => 1 } @{$pins->{directories}};
keys(%{$pins->{files}}) <= 4096 && keys(%{$pins->{links}}) <= 32 && keys(%dirs) <= 4096 or mismatch();
for my $name (keys %{$pins->{files}}, keys %{$pins->{links}}, keys %dirs) {
    $name =~ /\Apython(?:\/[A-Za-z0-9_.+\/-]+)?\z/ && $name !~ /(?:\A|\/)\.\.(?:\/|\z)/ or mismatch();
}
for my $name (keys %{$pins->{links}}) {
    my $target=$pins->{links}{$name};
    $target =~ /\A[A-Za-z0-9_.+-]+\z/ && $target ne '.' && $target ne '..'
        && exists $pins->{files}{dirname($name).'/'.$target} && !exists $pins->{files}{$name} or mismatch();
}
for my $name (keys %{$pins->{files}}) {
    !exists $dirs{$name} && !exists $pins->{links}{$name} or mismatch();
}
my %seen;
find({ no_chdir => 1, follow => 0, wanted => sub {
    my $path = $File::Find::name;
    return if $path eq $root;
    my $name = substr($path, length($root) + 1);
    my @info = lstat($path); @info or mismatch();
    if (S_ISLNK($info[2])) {
        exists $pins->{links}{$name} && readlink($path) eq $pins->{links}{$name} or mismatch();
    } elsif (S_ISDIR($info[2])) {
        exists $dirs{$name} && !exists $pins->{files}{$name} && !exists $pins->{links}{$name} or mismatch();
    } elsif (S_ISREG($info[2])) {
        my $pin = $pins->{files}{$name}; $pin && $info[7] == $pin->{bytes} or mismatch();
        (!!($info[2] & 0111)) == (!!$pin->{executable}) or mismatch();
        open my $body, '<:raw', $path or mismatch();
        my $hash = Digest::SHA->new(256); $hash->addfile($body); close $body;
        $hash->hexdigest eq $pin->{sha256} or mismatch();
        my @after = lstat($path);
        @after && join(':', @info[0,1,2,7,9]) eq join(':', @after[0,1,2,7,9]) or mismatch();
    } else { mismatch(); }
    $seen{$name} = 1;
}}, $root);
for my $name (keys %{$pins->{files}}, keys %{$pins->{links}}, keys %dirs) {
    $seen{$name} or mismatch();
}
print "private_python_verified\n";
