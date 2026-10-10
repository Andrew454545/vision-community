"""System-only verification before an autonomous Mac launch executes Python.

The checked plist contains this small guard and the immutable source/runtime
pins. No downloaded code executes before its complete inventory is verified.
"""
import hashlib
from pathlib import Path

from community.mac_launch_agent import agent_config
from community.mac_runtime import INVENTORY_SHA256, PYTHON_FOLDER, PYTHON_RELATIVE
from community.mac_starter import regular, verify_snapshot

# Invoked through system env -i. Neither Perl startup options nor Python/Bash
# injection settings are inherited from the user's interactive environment.
GUARD = r'''
use strict; use warnings; use Digest::SHA; use File::Basename qw(dirname);
use Fcntl qw(:mode O_WRONLY O_CREAT O_EXCL);
my ($root,$source,$source_sha,$verifier_sha,$python_root,$python,@args)=@ARGV;
sub regular {
    my ($p,$dir,$missing)=@_;
    $p =~ m{\A/} && $p !~ m{(?:\A|/)\.\.?(?:/|\z)} or die "scope\n";
    my $parent=dirname($p);
    while ($parent ne '/') {
        my @s=lstat($parent); @s && S_ISDIR($s[2]) && !S_ISLNK($s[2]) or die "scope\n";
        $parent=dirname($parent);
    }
    my @s=lstat($p); return if !@s && $missing && !-e $p && !-l $p;
    @s && !S_ISLNK($s[2]) && ($dir ? S_ISDIR($s[2]) : S_ISREG($s[2])) or die "scope\n";
}
sub failure {
    # Never write through a redirected report directory or overwrite a report.
    eval {
        regular($root,1,0); my $folder="$root/setup-failures";
        regular($folder,1,1); mkdir($folder,0700) unless -d $folder;
        regular($folder,1,0);
        my $name="$folder/mac-background-".time()."-$$.json";
        if (sysopen(my $f,$name,O_WRONLY|O_CREAT|O_EXCL,0600)) {
            print $f '{"status":"INCOMPLETE","phase":"background-trust","code":"mac_background_trust_failed"}'; close $f;
        }
        regular("$root/NEEDS-ATTENTION",0,1);
        if (!-e "$root/NEEDS-ATTENTION") {
            sysopen(my $marker,"$root/NEEDS-ATTENTION",O_WRONLY|O_CREAT|O_EXCL,0600); close $marker if $marker;
        }
    };
    exit 1;
}
eval {
    regular($root,1,0);
    for my $name ('STOP-AFTER-BATCH','NEEDS-ATTENTION') {
        regular("$root/$name",0,1); exit 0 if -f "$root/$name";
    }
    index($source,"$root/apps/")==0 && index($python_root,"$root/")==0
        && index($python,"$python_root/")==0 or die "scope\n";
    regular($source,1,0); regular($python_root,1,0);
    $source_sha =~ /\A[a-f0-9]{64}\z/ && $verifier_sha =~ /\A[a-f0-9]{64}\z/ or die "pin\n";
    my $verifier="$source/macos/verify-source.pl"; regular($verifier,0,0);
    -s $verifier <= 65536 or die "pin\n";
    open my $f,'<:raw',$verifier or die "pin\n";
    my $hash=Digest::SHA->new(256); $hash->addfile($f); close $f;
    $hash->hexdigest eq $verifier_sha or die "pin\n";
    system('/usr/bin/perl',$verifier,$source,$source_sha)==0 or die "source\n";
    system('/usr/bin/perl',"$source/macos/verify-python.pl",
        "$source/macos/python-arm64-inventory.json",'__INVENTORY_SHA__',$python_root)==0 or die "python\n";
    regular($python,0,0);
    $ENV{SSL_CERT_FILE}="$python_root/python/lib/python3.14/site-packages/pip/_vendor/certifi/cacert.pem";
    exec($python,'-I','-B',"$source/community/mac_worker.py",@args) or die "exec\n";
};
failure();
'''.replace('__INVENTORY_SHA__', INVENTORY_SHA256)
# launchctl print represents each argument as a line. Keep this literal a single
# line so exact readback cannot confuse guard source with argument boundaries.
GUARD = ' '.join(line.strip() for line in GUARD.splitlines()
                 if line.strip() and not line.lstrip().startswith('#'))


def guarded_config(root, source, *, home, **settings):
    import json
    root = regular(root, directory=True)
    source = regular(source, directory=True)
    if source.parent != root / 'apps':
        raise ValueError('invalid_mac_background_scope')
    metadata = regular(source / 'source-inventory.json').read_bytes()
    if len(metadata) > 2 * 1024 * 1024:
        raise ValueError('invalid_mac_source')
    digest = hashlib.sha256(metadata).hexdigest()
    if source.name != digest:
        raise ValueError('invalid_mac_source')
    verify_snapshot(source, json.loads(metadata)['files'], metadata)
    python_root = regular(root / PYTHON_FOLDER, directory=True)
    python = regular(python_root / PYTHON_RELATIVE)
    entry = regular(source / 'community/mac_worker.py')
    config = agent_config(root, python, entry, home=home, **settings)
    verifier_sha = hashlib.sha256(regular(source / 'macos/verify-source.pl').read_bytes()).hexdigest()
    config['ProgramArguments'] = ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin:/usr/sbin:/sbin',
        'LC_ALL=C', 'HOME=' + str(regular(home, directory=True)), '/usr/bin/perl', '-e', GUARD,
        str(root), str(source), digest, verifier_sha, str(python_root), str(python),
        *config['ProgramArguments'][4:]]
    return config
