#!/usr/bin/python3


# nice apt-get -s -o Debug::NoLocking=true upgrade | grep ^Inst

import apt
import apt_pkg
import os
import sys
from optparse import OptionParser
import re
import gettext
import distro_info


SYNAPTIC_PINFILE = "/var/lib/synaptic/preferences"
OS_RELEASE_PATH = "/etc/os-release"
PRO_ESM_CACHE_DIR = "/var/lib/ubuntu-advantage/apt-esm/"


def _get_info_from_os_release(key):
    " get info directly from os-release file "
    if os.path.exists(OS_RELEASE_PATH):
        with open(OS_RELEASE_PATH) as f:
            search_res = re.search(
                r"{}=(?P<name>.*)".format(key),
                f.read()
            )
            if search_res:
                return search_res.group("name")
            else:
                raise Exception(
                    "Could not find {} in {}".format(
                        key, OS_RELEASE_PATH
                    )
                )
    else:
        raise Exception(
            "File {} was not found on the system".format(
                OS_RELEASE_PATH
            )
        )


def get_distro():
    " get distro name "
    return _get_info_from_os_release(key="UBUNTU_CODENAME")


DISTRO = "debian"

ESM_INFRA_ORIGIN = "UbuntuESM"
ESM_APPS_ORIGIN = "UbuntuESMApps"
ESM_ORIGINS = (ESM_INFRA_ORIGIN, ESM_APPS_ORIGIN)


def _(msg):
    return gettext.dgettext("update-notifier", msg)


def _handleException(type, value, tb):
    sys.stderr.write("E: " + _("Unknown Error: '%s' (%s)") % (type, value))
    sys.exit(-1)


def get_distro_version():
    " get distro version "
    return _get_info_from_os_release(key="VERSION_ID").replace('"', "")


def clean(cache, depcache):
    " unmark (clean) all changes from the given depcache "
    # mvo: looping is too inefficient with the new auto-mark code
    # for pkg in cache.Packages:
    #     depcache.MarkKeep(pkg)
    depcache.init()


def saveDistUpgrade(cache, depcache):
    """ this function mimics a upgrade but will never remove anything """
    depcache.upgrade(True)
    if depcache.del_count > 0:
        clean(cache, depcache)
    depcache.upgrade()


def isSecurityUpgrade(ver):
    " check if the given version is a security update (or masks one) "
    security_pockets = [("Ubuntu", "%s-security" % DISTRO),
                        (ESM_INFRA_ORIGIN, "%s-infra-security" % DISTRO),
                        (ESM_APPS_ORIGIN, "%s-apps-security" % DISTRO),
                        ("gNewSense", "%s-security" % DISTRO),
                        ("Debian", "%s-updates" % DISTRO)]
    for (file, index) in ver.file_list:
        for origin, archive in security_pockets:
            if (file.archive == archive and file.origin == origin):
                return True
    return False


def _isESMUpgrade(ver, esm_origin):
    " check if the given version is a security update (or masks one) "
    for (file, index) in ver.file_list:
        if file.origin == esm_origin and file.archive.startswith(DISTRO):
            return True
    return False


def isESMAppsUpgrade(ver):
    " check if the given version is an ESM Apps upgrade "
    return _isESMUpgrade(ver, esm_origin=ESM_APPS_ORIGIN)


def isESMInfraUpgrade(ver):
    " check if the given version is an ESM Infra upgrade "
    return _isESMUpgrade(ver, esm_origin=ESM_INFRA_ORIGIN)


def write_package_names(outstream, cache, depcache):
    " write out package names that change to outstream "
    pkgs = [pkg for pkg in cache.packages if depcache.marked_install(pkg)
            or depcache.marked_upgrade(pkg)]
    outstream.write("\n".join([p.name for p in pkgs]))


def is_esm_distro():
    " check if the current distro is ESM or not "
    ubuntu_distro = distro_info.UbuntuDistroInfo()

    is_esm_supported = bool(
        DISTRO in ubuntu_distro.supported_esm()
    )

    is_not_currently_supported = bool(
        DISTRO in ubuntu_distro.unsupported()
    )

    return is_esm_supported and is_not_currently_supported


def is_lts_distro():
    " check if the current distro is LTS or not"
    return distro_info.UbuntuDistroInfo().is_lts(DISTRO)


def _output_esm_package_count(outstream, service_type, esm_pkg_count):
    " output the number of packages upgrades related to esm service "
    if esm_pkg_count > 0:
        outstream.write("\n")
        outstream.write(gettext.dngettext("update-notifier",
                                          "%d of these updates "
                                          "is an ESM %s "
                                          "security update.",
                                          "%d of these updates "
                                          "are ESM %s "
                                          "security updates.",
                                          esm_pkg_count) %
                        (esm_pkg_count, service_type))


def _output_esm_package_alert(
    outstream, service_type, disabled_pkg_count, is_esm=False
):
    " output the number of upgradable packages if esm service was enabled "
    outstream.write("\n")
    if disabled_pkg_count > 0:
        outstream.write("\n")

        if is_esm:
            distro_version = get_distro_version()
            esm_info_url = "https://ubuntu.com/{}".format(
                distro_version.replace(".", "-")
            )
            learn_msg_suffix = "for Ubuntu {} at\n{}".format(
                distro_version, esm_info_url)
        else:
            learn_msg_suffix = "at https://ubuntu.com/esm"

        outstream.write(gettext.dngettext("update-notifier",
                                          "%i additional security "
                                          "update can be applied "
                                          "with ESM %s.\nLearn "
                                          "more about enabling ESM %s "
                                          "service %s",
                                          "%i additional security "
                                          "updates can be applied "
                                          "with ESM %s.\nLearn "
                                          "more about enabling "
                                          "ESM %s service %s",
                                          disabled_pkg_count) %
                        (disabled_pkg_count, service_type, service_type,
                         learn_msg_suffix))
    else:
        outstream.write("\n")
        outstream.write(gettext.dgettext("update-notifier",
                                         "Enable ESM %s to "
                                         "receive additional future "
                                         "security updates.") %
                        service_type)

        outstream.write("\n")
        outstream.write(
            gettext.dgettext("update-notifier",
                             "See https://ubuntu.com/esm "
                             "or run: sudo pro status")
        )


def _output_esm_service_status(outstream, have_esm_service, service_type):
    if have_esm_service:
        outstream.write(gettext.dgettext("update-notifier",
                                         "Expanded Security Maintenance for "
                                         "%s is enabled.") % service_type)
    else:
        outstream.write(gettext.dgettext("update-notifier",
                                         "Expanded Security Maintenance for "
                                         "%s is not enabled.") % service_type)
    outstream.write("\n\n")


def write_human_readable_summary(outstream, upgrades, security_updates,
                                 esm_infra_updates, esm_apps_updates,
                                 have_esm_infra, have_esm_apps,
                                 disabled_esm_infra_updates,
                                 disabled_esm_apps_updates):

    " write out human summary summary to outstream "
    esm_distro = is_esm_distro()
    lts_distro = is_lts_distro()

    if have_esm_infra is not None and esm_distro:
        _output_esm_service_status(
            outstream, have_esm_infra, service_type="Infrastructure"
        )

    if have_esm_apps is not None and lts_distro and not esm_distro:
        _output_esm_service_status(
            outstream, have_esm_apps, service_type="Applications"
        )

    outstream.write(
        gettext.dngettext("update-notifier",
                          "%i update can be applied immediately.",
                          "%i updates can be applied immediately.",
                          upgrades) % upgrades
    )

    _output_esm_package_count(
        outstream, service_type="Infra", esm_pkg_count=esm_infra_updates)
    _output_esm_package_count(
        outstream, service_type="Apps", esm_pkg_count=esm_apps_updates)

    if security_updates > 0:
        outstream.write("\n")
        outstream.write(gettext.dngettext("update-notifier",
                                          "%i of these updates is a "
                                          "standard security update.",
                                          "%i of these updates are "
                                          "standard security updates.",
                                          security_updates) %
                        security_updates)

    if any([upgrades, security_updates, esm_infra_updates, esm_apps_updates]):
        outstream.write("\n")
        outstream.write(gettext.dgettext("update-notifier",
                                         "To see these additional updates "
                                         "run: apt list --upgradable"))

    if all(
        [
            have_esm_apps is not None,
            not have_esm_apps,
            lts_distro,
            not esm_distro
        ]
    ):
        _output_esm_package_alert(
            outstream, service_type="Apps",
            disabled_pkg_count=disabled_esm_apps_updates)

    if have_esm_infra is not None and not have_esm_infra and esm_distro:
        _output_esm_package_alert(
            outstream, service_type="Infra",
            disabled_pkg_count=disabled_esm_infra_updates,
            is_esm=True
        )

    outstream.write("\n")


def has_disabled_esm_security_update(esm_cache, pkg, esm_origin):
    " check if we have a disabled ESM security update "
    inst_ver = pkg.current_ver
    if not inst_ver:
        return False

    if pkg.name not in esm_cache:
        return False

    esm_update = esm_cache[pkg.name]
    for version in esm_update.version_list:
        for (file, index) in version.file_list:
            if file.origin == esm_origin:
                return True

    return False


def has_disabled_esm_apps_security_update(esm_cache, pkg):
    " check if we have a disabled ESM Apps security update "
    return has_disabled_esm_security_update(esm_cache, pkg, ESM_APPS_ORIGIN)


def has_disabled_esm_infra_security_update(esm_cache, pkg):
    " check if we have a disabled ESM Infra security update "
    return has_disabled_esm_security_update(esm_cache, pkg, ESM_INFRA_ORIGIN)


def has_esm_service(cache, esm_origin):
    " check if we have an enabled ESM service in the machine "
    for file in cache.file_list:
        origin = file.origin
        if origin == esm_origin and file.archive.startswith(DISTRO):
            return True

    return False


def get_apt_pkg_esm_cache():
    """Get an apt_pkg cache with the ubuntu-advantage-tools esm data.

    Set the configuration to get the u-a-t cache, then set it back to an
    empty configuration state and init again so other calls to Cache work as
    expected.
    """
    for key in apt_pkg.config.keys():
        if re.match(r"^Acquire", key) is None:
            apt_pkg.config.clear(key)
    apt_pkg.config.set("Dir", PRO_ESM_CACHE_DIR)
    apt_pkg.init()
    try:
        esm_cache = apt_pkg.Cache(progress=None)
    except apt_pkg.Error:
        esm_cache = None

    for key in apt_pkg.config.keys():
        apt_pkg.config.clear(key)
    apt_pkg.init()

    return esm_cache


def init():
    " init the system, be nice "
    # FIXME: do a ionice here too?
    os.nice(19)
    apt_pkg.init()


def run(options=None):

    # we are run in "are security updates installed automatically?"
    # question mode
    if options.security_updates_unattended:
        res = apt_pkg.config.find_i("APT::Periodic::Unattended-Upgrade", 0)
        # print(res)
        sys.exit(res)

    # get caches
    try:
        cache = apt_pkg.Cache(apt.progress.base.OpProgress())
    except SystemError as e:
        sys.stderr.write("E: " + _("Error: Opening the cache (%s)") % e)
        sys.exit(-1)
    depcache = apt_pkg.DepCache(cache)

    # read the synaptic pins too
    if os.path.exists(SYNAPTIC_PINFILE):
        depcache.read_pinfile(SYNAPTIC_PINFILE)
        depcache.init()

    if depcache.broken_count > 0:
        sys.stderr.write("E: " + _("Error: BrokenCount > 0"))
        sys.exit(-1)

    # do the upgrade (not dist-upgrade!)
    try:
        saveDistUpgrade(cache, depcache)
    except SystemError as e:
        sys.stderr.write("E: " + _("Error: Marking the upgrade (%s)") % e)
        sys.exit(-1)

    esm_cache = get_apt_pkg_esm_cache()

    # Check if we have ESM enabled or disabled; and if it exists in the
    # first place.
    have_esm_infra = has_esm_service(cache, esm_origin=ESM_INFRA_ORIGIN)
    have_esm_apps = has_esm_service(cache, esm_origin=ESM_APPS_ORIGIN)

    # analyze the ugprade
    upgrades = 0
    security_updates = 0
    esm_apps_updates = 0
    esm_infra_updates = 0
    disabled_esm_apps_updates = 0
    disabled_esm_infra_updates = 0

    # we need another cache that has more pkg details
    with apt.Cache() as aptcache:
        for pkg in cache.packages:
            if esm_cache:
                if has_disabled_esm_apps_security_update(esm_cache, pkg):
                    disabled_esm_apps_updates += 1
                if has_disabled_esm_infra_security_update(esm_cache, pkg):
                    disabled_esm_infra_updates += 1

            # skip packages that are not marked upgraded/installed
            if not (depcache.marked_install(pkg)
                    or depcache.marked_upgrade(pkg)):
                continue
            # check if this is really a upgrade or a false positive
            # (workaround for ubuntu #7907)
            inst_ver = pkg.current_ver
            cand_ver = depcache.get_candidate_ver(pkg)
            if cand_ver == inst_ver:
                continue
            # check for security upgrades
            if isSecurityUpgrade(cand_ver):
                if have_esm_apps and isESMAppsUpgrade(cand_ver):
                    esm_apps_updates += 1
                elif have_esm_infra and isESMInfraUpgrade(cand_ver):
                    esm_infra_updates += 1
                else:
                    security_updates += 1

                upgrades += 1
                continue

            # check to see if the update is a phased one
            try:
                from UpdateManager.Core.UpdateList import UpdateList
                ul = UpdateList(None)
                ignored = ul._is_ignored_phased_update(
                    aptcache[pkg.get_fullname()])
                if ignored:
                    depcache.mark_keep(pkg)
                    continue
            except ImportError:
                pass

            upgrades = upgrades + 1

            # now check for security updates that are masked by a
            # candidate version from another repo (-proposed or -updates)
            for ver in pkg.version_list:
                if (inst_ver
                        and apt_pkg.version_compare(ver.ver_str,
                                                    inst_ver.ver_str) <= 0):
                    continue
                if have_esm_apps and isESMAppsUpgrade(cand_ver):
                    esm_apps_updates += 1
                elif have_esm_infra and isESMInfraUpgrade(cand_ver):
                    esm_infra_updates += 1
                elif isSecurityUpgrade(ver):
                    security_updates += 1
                    break

    # print the number of upgrades
    if options and options.show_package_names:
        write_package_names(sys.stderr, cache, depcache)
    elif options and options.readable_output:
        write_human_readable_summary(sys.stdout, upgrades, security_updates,
                                     esm_infra_updates, esm_apps_updates,
                                     have_esm_infra, have_esm_apps,
                                     disabled_esm_infra_updates,
                                     disabled_esm_apps_updates)
    else:
        # print the number of regular upgrades and the number of
        # security upgrades
        sys.stderr.write("%s;%s" % (upgrades, security_updates))

    # return the number of upgrades (if its used as a module)
    return(upgrades, security_updates)


if __name__ == "__main__":
    # setup a exception handler to make sure that uncaught stuff goes
    # to the notifier
    sys.excepthook = _handleException

    # gettext
    APP = "update-notifier"
    DIR = "/usr/share/locale"
    gettext.bindtextdomain(APP, DIR)
    gettext.textdomain(APP)

    # check arguments
    parser = OptionParser()
    parser.add_option("-p",
                      "--package-names",
                      action="store_true",
                      dest="show_package_names",
                      help=_("Show the packages that are "
                             "going to be installed/upgraded"))
    parser.add_option("",
                      "--human-readable",
                      action="store_true",
                      dest="readable_output",
                      help=_("Show human readable output on stdout"))
    parser.add_option("",
                      "--security-updates-unattended",
                      action="store_true",
                      help=_("Return the time in days when security updates "
                             "are installed unattended (0 means disabled)"))
    (options, args) = parser.parse_args()

    # run it
    init()
    run(options)
